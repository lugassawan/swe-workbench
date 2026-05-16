---
name: workflow-pr-review-followup
description: Use when a reviewer wants to re-check a PR after the owner has addressed feedback — re-runs the reviewer agent against the updated diff, deduplicates against existing threads (Jaccard ±5-line), posts only truly-new inline comments, and submits an APPROVE or COMMENT review event.
orchestrator: true
---

# Workflow: PR Review Follow-up

**Announce at start:** "I'm using the workflow-pr-review-followup skill to re-check PR #N."

## When to invoke

- The user runs `/swe-workbench:review --check-followup <N>`.
- A reviewer has already posted a full review and wants to verify that their findings were addressed.
- Phrases: "re-check PR 123", "check if my review comments were addressed", "follow up on review #456".

## When NOT to invoke

- Full first-pass review → use `swe-workbench:workflow-pr-review` instead.
- The PR is closed/merged → out of scope.

## Composition

This skill orchestrates; analysis is delegated to:

- `swe-workbench:reviewer` subagent — produces `Severity | File:Line | Issue | Why | Fix` findings + a Review Decision footer.
- `swe-workbench:ticket-context` skill — prepended when PR references a ticket key.

## 7-step flow

### Step 1 — Pre-flight

```bash
gh auth status >/dev/null || { echo "gh not authenticated. Run 'gh auth login'."; exit 1; }
CURRENT_USER=$(gh api /user -q .login)
mkdir -p /tmp/swe-workbench-pr-review
gh pr view "$PR" --json state,number,headRefName,baseRefName,headRepository,headRefOid,title,body,author \
  > "/tmp/swe-workbench-pr-review/${PR}-followup.json"
[ -s "/tmp/swe-workbench-pr-review/${PR}-followup.json" ] || { echo "PR #$PR not found or not accessible."; exit 1; }
```

Extract `BASE`, `HEAD_SHA`, `OWNER`, `REPO`, and `AUTHOR_LOGIN` (from `author.login`) from the JSON. The state file is stored under `${PR}-followup.json` (distinct from `${PR}.json` used by the primary review) to allow both to coexist.

Check that the PR is open before proceeding:
```bash
STATE=$(jq -r .state "/tmp/swe-workbench-pr-review/${PR}-followup.json")
[ "$STATE" = "OPEN" ] || { echo "PR #$PR is $STATE — follow-up review only applies to open PRs."; exit 1; }
```

### Step 2 — Ephemeral worktree

**When rimba is available** (preferred — handles cross-fork remotes automatically and skips dep installation):

```bash
RIMBA_OUT=$(rimba add pr:$PR --task "pr-followup-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

The task is named `pr-followup-$PR` (NOT `pr-review-$PR`) so cleanup of the primary-review worktree does not collide with this one. `--skip-deps` suppresses dep installation; `--skip-hooks` suppresses post-create hooks — both unnecessary for a read-only diff review.

**When rimba is absent** (fallback — direct git, NOT `superpowers:using-git-worktrees` which is consent-gated for durable feature work):

```bash
WT="/tmp/swe-workbench-pr-review/${PR}-followup"
if [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || rm -rf "$WT"
fi
mkdir -p "$(dirname "$WT")"
git fetch origin "pull/${PR}/head:pr-followup-${PR}" --force
git worktree add --detach "$WT" "pr-followup-${PR}"
```

### Step 3 — Ticket-context chain

Identical to `workflow-pr-review` Step 3. Read `title` and `body` from the saved JSON. Match `[A-Z]+-\d+`, atlassian/Confluence URLs, or `#\d+`/PR refs in either field plus the last 5 commit messages. If matched, invoke `swe-workbench:ticket-context` and capture its summary as a prelude.

### Step 4 — Invoke `reviewer`

Pass the agent:
- Working-directory hint: absolute path of the worktree (`$WT`).
- Diff: `git -C "$WT" diff "$BASE"..HEAD`.
- Repo-relative-path instruction (load-bearing — strip the `$WT/` prefix before the colon):
  > "Emit **repo-relative** paths in every finding (e.g. `src/foo.ts:42`, NOT `$WT/src/foo.ts:42`). The orchestrator uses these paths to position GitHub comments."
- Footer instruction (load-bearing — opt-in per the agent's `## Decision footer (when instructed)` block):
  > "End the review with EXACTLY ONE of `**Review Decision: APPROVE**` or `**Review Decision: COMMENT**` on its own line, no prefix or trailing text. Never `REQUEST_CHANGES`."
- Narrative instruction (load-bearing — opt-in per the agent's `## Review Summary (when instructed)` block):
  > "Begin the review with a `## Review Summary` section: 2–4 sentences capturing overall posture, the strongest positives, and the most important concerns. When the reviewer is not the PR author, the orchestrator uses these paragraphs as the top-level PR review body; otherwise the narrative is shown in the Claude session only and not posted to GitHub. Do not repeat per-finding detail there — that goes in the severity-grouped findings below."
- Ticket-context prelude (if Step 3 produced one).

Store the agent's complete text response as `REVIEWER_OUTPUT`.

### Step 5 — Parse decision footer

Scan ALL non-blank lines for the footer pattern:

```
^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$
```

Abort with "reviewer agent did not emit a valid Review Decision footer (APPROVE|COMMENT). Refusing to submit." if ANY of:
- Zero matches found.
- More than one matching line found.
- `REQUEST_CHANGES` appears anywhere in the agent output.

Do NOT clean up the worktree on abort — leave it for inspection.

### Step 6 — Dedup + post inline comments

1. **Fetch existing review threads** via GraphQL:

   ```bash
   gh api graphql -F number="$PR" -F owner="$OWNER" -F repo="$REPO" -f query='
     query($owner: String!, $repo: String!, $number: Int!) {
       repository(owner: $owner, name: $repo) {
         pullRequest(number: $number) {
           reviewThreads(first: 100) {
             nodes {
               id isResolved path line startLine
               comments(first: 10) {
                 nodes {
                   id databaseId body
                   author { login }
                   reactions(first: 20, content: THUMBS_UP) {
                     nodes { user { login } }
                   }
                 }
               }
             }
           }
         }
       }
     }' > "/tmp/swe-workbench-pr-review/${PR}-followup-threads.json"
   ```

2. **For each new finding** (parsed from `Severity | File:Line | Issue | Why | Fix` row):

   - **Fuzzy-match** against fetched threads, against ANY author:
     - Same `path`.
     - `|finding.line - thread.line| ≤ 5` (use `startLine` for multi-line ranges).
     - Body Jaccard token overlap ≥ 0.4 (cheap content-similarity proxy).
     - `isResolved == false`.
   - **On match**: skip posting. If `$CURRENT_USER` has not already 👍'd (check `reactions.nodes[].user.login`), add a 👍 to the thread head (first comment's `id`):

     ```bash
     gh api graphql -F subjectId="$THREAD_HEAD_ID" -f query='
       mutation($subjectId: ID!) {
         addReaction(input: {subjectId: $subjectId, content: THUMBS_UP}) { reaction { id } }
       }'
     ```

   - **On no match**: post a new inline comment via REST:

     ```bash
     gh api "repos/${OWNER}/${REPO}/pulls/${PR}/comments" \
       -F body="$BODY" \
       -F path="$REPO_PATH" \
       -F line="$LINE" \
       -F side=RIGHT \
       -F commit_id="$HEAD_SHA"
     ```

3. Track counts: `posted=N`, `deduped=M`.

### Step 7 — Submit + cleanup

Build `$SUMMARY` from `$REVIEWER_OUTPUT` (captured in Step 4):

```bash
NARRATIVE=$(awk '
  /^[[:space:]]*(Critical|High|Medium|Low|Severity)[[:space:]]*\|/ { exit }
  /^###[[:space:]]+(Critical|High|Medium|Low)\b/ { exit }
  /^\*\*Review Decision:/ { exit }
  { print }
' <<< "$REVIEWER_OUTPUT" | sed -e '/^[[:space:]]*$/d' -e '/^## Review Summary[[:space:]]*$/d')
HAS_NARRATIVE="$([ -n "$(echo "$NARRATIVE" | tr -d '[:space:]')" ] && echo true || echo false)"
IS_SELF_REVIEW="$([ -n "$CURRENT_USER" ] && [ -n "$AUTHOR_LOGIN" ] && [ "$CURRENT_USER" = "$AUTHOR_LOGIN" ] && echo true || echo false)"

# $posted and $deduped are set in Step 6.
BYLINE="_Re-reviewed by \`reviewer\` ([swe-workbench](https://github.com/lugassawan/swe-workbench)). Posted ${posted} inline comments, deduped ${deduped}._"

if [ "$HAS_NARRATIVE" = true ] && [ "$IS_SELF_REVIEW" = false ]; then
  SUMMARY=$(printf '## Review Summary\n\n%s\n\nDetailed feedback in inline comments.\n\n**Review Decision: %s**\n\n---\n%s\n' \
    "$NARRATIVE" "$DECISION" "$BYLINE")
else
  # Reused for empty-narrative AND self-review.
  SUMMARY="$BYLINE"
fi
```

Submit per the parsed decision:
- `APPROVE` → `gh pr review "$PR" --approve --body "$SUMMARY"`
- `COMMENT` → `gh pr review "$PR" --comment --body "$SUMMARY"`

**Never** use `--request-changes`.

**Address-feedback CTA (conditional):** After the submit call succeeds, if `CURRENT_USER != AUTHOR_LOGIN`, append:

> "Want me to help the PR owner address this feedback? Reply `yes` to start `/address-feedback <N>`."

Suppress this CTA silently when `CURRENT_USER == AUTHOR_LOGIN`.

Cleanup non-blocking:
```bash
( rimba remove "pr-followup-$PR" --force 2>/dev/null \
  || { git worktree remove --force "$WT" 2>/dev/null; \
       git branch -D "pr-followup-$PR" 2>/dev/null; \
       rm -rf "$WT" 2>/dev/null; } ) &
```

## Footer parsing contract

Identical to `workflow-pr-review`:
- Regex: `^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$`
- Source: scan ALL non-blank lines of agent output.
- Abort cases (do NOT submit, preserve worktree):
  - Zero matches.
  - More than one matching line.
  - `REQUEST_CHANGES` appears anywhere in the agent output.

## Dedup contract

Identical to `workflow-pr-review`:
1. `T.path == finding.path` (exact, repo-relative).
2. `|T.line - finding.line| ≤ 5` (if `T.startLine` is null, use `T.line`; otherwise use `T.startLine`).
3. Jaccard overlap of word tokens between `T.comments[0].body` and `finding.body` ≥ 0.4.
4. `T.isResolved == false`.

Match against ANY author. On match, skip posting AND add 👍 to the thread head if our user hasn't already reacted.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth status` fails | Non-zero exit | Abort. Print fix hint. |
| PR not open / 404 | `gh pr view` fails | Abort. |
| `git fetch pull/N/head` fails | Non-zero exit | Abort. Do not create worktree. |
| Reviewer aborts mid-scan | Agent error | Skip submit. **Leave worktree** for inspection. |
| Decision footer missing or malformed | Regex no-match | Abort with explicit message. Worktree preserved. |
| Comment-post returns 422 (line out of range) | HTTP 422 | Skip that finding, log "skipped (line out of range)", continue. |
| All POSTs returned 422 (stale `commit_id` — PR head advanced between Step 1 and Step 6) | `posted == 0` AND every finding skipped with 422 | Re-fetch `HEAD_SHA` via `gh pr view "$PR" --json headRefOid -q .headRefOid` and retry once. If still failing, abort with "HEAD_SHA mismatch — PR updated mid-review". |
| All findings dedup-matched | `posted == 0` | Submit with body "no new findings — all previously raised". Decision footer still respected. |
| GraphQL pagination needed (PR > 100 threads) | `hasNextPage == true` | Document as known v1 limit. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Use `--task "pr-review-$PR"` for the worktree | Use `--task "pr-followup-$PR"` to avoid colliding with a still-active primary-review worktree. |
| Omit the footer instruction in Step 4 | Without it, the agent does NOT emit the footer. Step 5 will then abort. |
| Forget repo-relative-path instruction | GitHub comment positioning requires repo-relative paths. The agent will emit `$WT/...` paths otherwise. |
| Skip the narrative instruction in Step 4 | Without it, the reviewer does NOT emit `## Review Summary` (per its `## Review Summary (when instructed)` block). Step 7 falls back to the BYLINE-only branch silently — body is not wrong but loses the prose narrative for cross-author reviews (self-review intentionally produces BYLINE-only; see row below). |
| Emit the address-feedback CTA when `CURRENT_USER == AUTHOR_LOGIN` | Always suppress for self-review. |
| Post `## Review Summary` on self-review | Step 7 gates narrative inclusion on `IS_SELF_REVIEW = false` — same policy axis as the address-feedback CTA suppression above. The narrative is still presented in the author's Claude session; only the GitHub-posted body is BYLINE-only. |
