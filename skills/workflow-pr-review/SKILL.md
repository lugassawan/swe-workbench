---
name: workflow-pr-review
description: Use when reviewing a remote GitHub PR — fetches into an ephemeral worktree, runs the reviewer agent with a Review Decision footer instruction, deduplicates findings against existing review threads (±5-line fuzzy match + Jaccard ≥ 0.4 against any author), posts new inline comments via gh-api, adds 👍 reactions on dedup matches, and submits the review with APPROVE or COMMENT. Counterpart of local-diff review (which workflow-development Phase 4 keeps using).
orchestrator: true
---

# Workflow: PR Review (remote-PR orchestration shell)

**Announce at start:** "I'm using the workflow-pr-review skill to review PR #N."

## When to invoke

- The user passes a PR number to `/swe-workbench:review` (e.g. `/review 123`).
- The user accepts the auto-detect prompt on `/review` no-arg ("Detected PR #N — review it? Reply `yes`").
- An agent or command needs to "review this remote PR end-to-end" — fetch + analyse + post + submit.
- Phrases: "review PR 123", "do a peer review of #456", "fetch this PR and post deduped comments".

## When NOT to invoke

- Local-diff review (working tree / staged / branch diff) → use `commands/review.md` no-arg directly. The command stays the entrypoint for local-diff mode.
- `workflow-development` Phase 4 → keeps using local-diff review (no remote PR exists yet during implementation).
- The user wants to post a single comment without running a full review → out of scope.
- The PR is closed/merged → out of scope; reviews target open PRs.

## Composition

This skill orchestrates; analysis is delegated to:

- `swe-workbench:reviewer` subagent — produces `Severity | File:Line | Issue | Why | Fix` findings + a Review Decision footer (when instructed by this skill — see Step 4).
- `swe-workbench:ticket-context` skill — prepended to the reviewer prompt when the PR body or commit messages reference a ticket key, atlassian/Confluence URL, or `#NNN` GitHub ref.

## 7-step flow

### Step 1 — Pre-flight

```bash
gh auth status >/dev/null || { echo "gh not authenticated. Run 'gh auth login'."; exit 1; }
CURRENT_USER=$(gh api /user -q .login)
mkdir -p /tmp/swe-workbench-pr-review
gh pr view "$PR" --json state,number,headRefName,baseRefName,baseRepository,headRefOid,title,body,author \
  > "/tmp/swe-workbench-pr-review/${PR}.json"
[ -s "/tmp/swe-workbench-pr-review/${PR}.json" ] || { echo "PR #$PR not found or not accessible."; exit 1; }
```

Extract fields from the JSON:

```bash
JSON="/tmp/swe-workbench-pr-review/${PR}.json"
BASE=$(jq -r .baseRefName "$JSON")
HEAD_SHA=$(jq -r .headRefOid "$JSON")
AUTHOR_LOGIN=$(jq -r .author.login "$JSON")
OWNER=$(jq -r '.baseRepository.owner.login // (.baseRepository.nameWithOwner // "" | split("/")[0])' "$JSON")
REPO=$(jq  -r '.baseRepository.name      // (.baseRepository.nameWithOwner // "" | split("/")[1])' "$JSON")
if [ -z "$OWNER" ] || [ "$OWNER" = "null" ] || [ -z "$REPO" ] || [ "$REPO" = "null" ]; then
  echo "Could not determine base repo owner/name from PR #$PR metadata. Inspect with: gh pr view $PR --json baseRepository" >&2
  exit 1
fi
```

### Step 2 — Ephemeral worktree

**When rimba is available** (preferred — handles cross-fork remotes automatically and skips dep installation):

```bash
RIMBA_OUT=$(rimba add pr:$PR --task "pr-review-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

rimba registers the task as `pr-review-<PR>` (overriding its default `review/<N>-<slug>` derivation) and places the worktree in the configured worktrees base directory. `--skip-deps` suppresses dep installation; `--skip-hooks` suppresses post-create hooks — both unnecessary for a read-only diff review.

**When rimba is absent** (fallback — direct git, NOT `superpowers:using-git-worktrees` which is consent-gated for durable feature work):

```bash
WT="/tmp/swe-workbench-pr-review/${PR}"
if [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || rm -rf "$WT"
fi
mkdir -p "$(dirname "$WT")"
git fetch origin "pull/${PR}/head:pr-review-${PR}" --force
git worktree add --detach "$WT" "pr-review-${PR}"
```

### Step 3 — Ticket-context chain

Read `title` and `body` from the saved JSON. Match `[A-Z]+-\d+`, atlassian/Confluence URLs, or `#\d+`/PR refs in either field plus the last 5 commit messages (`git -C "$WT" log --oneline -5`). If matched, invoke `swe-workbench:ticket-context` and capture its summary as a prelude to the reviewer prompt.

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

Store the agent's complete text response as `REVIEWER_OUTPUT` before Step 7 runs — in practice the orchestrator assigns the subagent's full text reply to this variable. Step 7's awk block reads from it via `<<< "$REVIEWER_OUTPUT"`.

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
     }' > "/tmp/swe-workbench-pr-review/${PR}-threads.json"
   ```

   Pagination via `pageInfo { endCursor hasNextPage }` if a real PR exceeds 100 threads.

2. **For each new finding** (parsed from `Severity | File:Line | Issue | Why | Fix` row):

   - **Fuzzy-match** against fetched threads, against ANY author (User Decision 2):
     - Same `path`.
     - `|finding.line - thread.line| ≤ 5` (use `startLine` for multi-line ranges).
     - Body Jaccard token overlap ≥ 0.4 (cheap content-similarity proxy).
     - `isResolved == false`.
   - **On match**: skip posting. If `$CURRENT_USER` has not already 👍'd (check `reactions.nodes[].user.login`; use `reactions(first: 20, ...)` — 5 truncates busy threads), add a 👍 to the thread head (first comment's `id`):

     ```bash
     gh api graphql -F subjectId="$THREAD_HEAD_ID" -f query='
       mutation($subjectId: ID!) {
         addReaction(input: {subjectId: $subjectId, content: THUMBS_UP}) { reaction { id } }
       }'
     ```

   - **On no match**: post a new inline comment via REST (supports `line=` directly):

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
if [ -z "$CURRENT_USER" ] || [ -z "$AUTHOR_LOGIN" ]; then
  echo "[warn] IS_SELF_REVIEW: identity unknown (CURRENT_USER='$CURRENT_USER' AUTHOR_LOGIN='$AUTHOR_LOGIN'); treating as cross-author." >&2
  IS_SELF_REVIEW=false
elif [ "$CURRENT_USER" = "$AUTHOR_LOGIN" ]; then
  IS_SELF_REVIEW=true
else
  IS_SELF_REVIEW=false
fi

# $posted and $deduped are set in Step 6.
BYLINE="_Reviewed by \`reviewer\` ([swe-workbench](https://github.com/lugassawan/swe-workbench)). Posted ${posted} inline comments, deduped ${deduped}._"

if [ "$HAS_NARRATIVE" = true ] && [ "$IS_SELF_REVIEW" = false ]; then
  SUMMARY=$(printf '## Review Summary\n\n%s\n\nDetailed feedback in inline comments.\n\n**Review Decision: %s**\n\n---\n%s\n' \
    "$NARRATIVE" "$DECISION" "$BYLINE")
elif [ "$IS_SELF_REVIEW" = false ]; then
  # No narrative but cross-author: post just the byline.
  SUMMARY="$BYLINE"
else
  # Self-review: nothing posted to GitHub; inline comments speak for themselves.
  SUMMARY=""
fi
```

Submit only when `IS_SELF_REVIEW = false` — GitHub blocks self-approval, and for self-review the Step 6 inline comments are sufficient without a review-event body:
- `APPROVE` → `gh pr review "$PR" --approve --body "$SUMMARY"`
- `COMMENT` → `gh pr review "$PR" --comment --body "$SUMMARY"`

When `IS_SELF_REVIEW = true`, skip the review-event submission entirely.

**Never** use `--request-changes`.

**Address-feedback CTA (conditional):** At the end of Step 7, when the review produced something actionable — i.e. `DECISION = COMMENT`, OR `posted > 0`, OR `deduped > 0` (existing open threads were re-confirmed; they still need addressing) — call the `AskUserQuestion` tool:

```json
{
  "questions": [{
    "question": "Want me to help address this feedback? Start /address-feedback <N>?",
    "header": "Next step",
    "multiSelect": false,
    "options": [
      { "label": "Yes — address feedback", "description": "Starts /address-feedback <N> to drive fixes end-to-end." },
      { "label": "No thanks",              "description": "Stay here; no further action." }
    ]
  }]
}
```

Substitute the real PR number for `<N>` in the question text and in the `Yes — address feedback` option description. On `Yes — address feedback` → invoke `/address-feedback <N>`. On `No thanks` (or any other answer) → no further action.

Identity does not gate the CTA — when the user has invoked Claude to review their own PR, they have explicitly opted into Claude's help; if findings are actionable, offering to drive `/address-feedback` is the natural next step regardless of authorship.

Suppress this CTA silently when `DECISION = APPROVE` and `posted = 0` and `deduped = 0` — a clean approval with no feedback has nothing to address; the CTA misrepresents the review.

Cleanup non-blocking:
```bash
( rimba remove "pr-review-$PR" --force 2>/dev/null \
  || { git worktree remove --force "$WT" 2>/dev/null; \
       git branch -D "pr-review-$PR" 2>/dev/null; \
       rm -rf "$WT" 2>/dev/null; } ) &
```

`rimba remove` deletes both the worktree and the local `pr-review-<N>` branch (task name pinned via `--task` in Step 2 to keep it consistent). The `git worktree remove` + `git branch -D` group is the defensive fallback for rimba-absent or rimba-failure environments.

## Footer parsing contract

- Regex: `^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$`
- Source: scan ALL non-blank lines of agent output.
- Abort cases (do NOT submit, preserve worktree):
  - Zero matches.
  - More than one matching line.
  - `REQUEST_CHANGES` appears anywhere in the agent output.

## Dedup contract

A new finding `(path, line, body)` matches an existing thread `T` IFF:
1. `T.path == finding.path` (exact, repo-relative).
2. `|T.line - finding.line| ≤ 5` (if `T.startLine` is null, use `T.line`; otherwise use `T.startLine`).
3. Jaccard overlap of word tokens between `T.comments[0].body` and `finding.body` ≥ 0.4.
4. `T.isResolved == false`.

Match against ANY author (User Decision 2). On match, skip posting AND add 👍 to the thread head if our user hasn't already reacted.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth status` fails | Non-zero exit | Abort. Print fix hint. |
| PR not open / 404 | `gh pr view` fails | Abort. Print PR URL if known. |
| `git fetch pull/N/head` fails | Non-zero exit | Abort. Do not create worktree. |
| Reviewer aborts mid-scan | Agent error | Skip submit. **Leave worktree** for inspection (do not remove). |
| Decision footer missing or malformed | Regex no-match | Abort with explicit message. Worktree preserved. |
| Comment-post returns 422 (line out of range) | HTTP 422 | Skip that finding, log "skipped (line out of range)", continue. |
| All POSTs returned 422 (stale `commit_id` — PR head advanced between Step 1 and Step 6) | `posted == 0` AND every finding skipped with 422 | The cached `$HEAD_SHA` (from Step 1) is provably stale here — 422 on every POST means the PR head advanced. Re-fetch a fresh SHA via `gh pr view "$PR" --json headRefOid -q .headRefOid` and retry once. If still failing, abort with "HEAD_SHA mismatch — PR updated mid-review". |
| All findings dedup-matched | `posted == 0` | Submit with body "no new findings — all previously raised". Decision footer still respected. |
| GraphQL pagination needed (PR > 100 threads) | `hasNextPage == true` | Loop with `after: endCursor`. Document as known limit if not implemented in v1. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Use `superpowers:using-git-worktrees` for the PR worktree | That skill is consent-gated and durable-feature-oriented. Use `rimba add pr:$PR --task "pr-review-$PR" --skip-deps --skip-hooks` when rimba is available; direct `git worktree add` otherwise. |
| Forget repo-relative-path instruction | GitHub comment positioning requires repo-relative paths. The agent will emit `$WT/...` paths otherwise — comments won't anchor. |
| Skip the footer instruction | Without it, the agent does NOT emit the footer (per its `## Decision footer (when instructed)` block). Step 5 will then abort. |
| Use `--request-changes` | Never. APPROVE / COMMENT only. The agent footer never produces this value. |
| Parse threads from REST `pulls/{N}/comments` | REST returns review-comment-by-comment; threading is reconstructed by the GraphQL `reviewThreads` shape. Use GraphQL to fetch, REST to post. |
| Force-add 👍 to your own existing comment | Check `reactions.nodes[].user.login` first; skip if you've already reacted. |
| Block on cleanup | Cleanup runs in background `(... ) &`. Don't `wait` for it. |
| Skip the narrative instruction in Step 4 | Without it, the reviewer does NOT emit `## Review Summary` (per its `## Review Summary (when instructed)` block). Step 7 falls back to the BYLINE-only branch silently — body is not wrong but loses the prose narrative for cross-author reviews (self-review intentionally produces BYLINE-only; see "Post `## Review Summary` on self-review" row). |
| Emit the address-feedback CTA when there is nothing to address | The CTA is gated on outcome only: call `AskUserQuestion` when `DECISION = COMMENT` OR `posted > 0` OR `deduped > 0`. Suppress on clean approvals (APPROVE with `posted = 0` and `deduped = 0`). Self-review is NOT a suppression trigger. |
| Emit the CTA as plain text instead of `AskUserQuestion` | Always use the `AskUserQuestion` tool for the CTA — it gives the user a clickable button and eliminates the "type yes" friction. Never emit a free-text prompt asking the user to reply `yes`. |
| Post `## Review Summary` on self-review | Step 7 gates narrative inclusion on `IS_SELF_REVIEW = false`. This is a distinct policy axis from the address-feedback CTA, which is gated on outcome only (not identity). The narrative is still presented in the author's Claude session; only the GitHub-posted body is BYLINE-only. |
