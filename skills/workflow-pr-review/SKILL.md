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
- **Checkpoint:** write the workflow state file (see `docs/workflow-state.md`) at each step boundary, carrying `$PR`/`$BASE`/`$HEAD_SHA`/`$DECISION` in `context`. Delete the state file after Step 7.

## 7-step flow

### Step 1 — Pre-flight

```bash
gh auth status >/dev/null || { echo "gh not authenticated. Run 'gh auth login'."; exit 1; }
CURRENT_USER=$(gh api /user -q .login)
mkdir -p /tmp/swe-workbench-pr-review
gh pr view "$PR" --json state,number,headRefName,baseRefName,headRefOid,title,body,author \
  > "/tmp/swe-workbench-pr-review/${PR}.json"
[ -s "/tmp/swe-workbench-pr-review/${PR}.json" ] || { echo "PR #$PR not found or not accessible."; exit 1; }
```

Extract fields from the JSON:

```bash
JSON="/tmp/swe-workbench-pr-review/${PR}.json"
BASE=$(jq -r .baseRefName "$JSON")
HEAD_SHA=$(jq -r .headRefOid "$JSON")
AUTHOR_LOGIN=$(jq -r .author.login "$JSON")
OWNER=$(gh repo view --json owner -q .owner.login)
REPO=$(gh repo view --json name   -q .name)
if [ -z "$OWNER" ] || [ "$OWNER" = "null" ] || [ -z "$REPO" ] || [ "$REPO" = "null" ]; then
  echo "Could not determine base repo owner/name. Run 'gh repo view' to verify the current remote is set correctly." >&2
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

**When rimba is absent** (fallback — direct git, NOT `superpowers:using-git-worktrees` which is consent-gated for durable feature work):

```bash
WT="/tmp/swe-workbench-pr-review/${PR}"
if [ -d "$WT" ]; then
  git worktree remove --force "$WT" 2>/dev/null || bash "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/scripts/clean-ephemeral.sh" "$WT" 2>/dev/null
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
- Repo-relative-path instruction (load-bearing): emit **repo-relative** paths (e.g. `src/foo.ts:42`, NOT `$WT/src/foo.ts:42`). The orchestrator uses these paths to position GitHub comments.
- Footer instruction (opt-in per `## Decision footer`): end with EXACTLY ONE of `**Review Decision: APPROVE**` or `**Review Decision: COMMENT**`. Never `REQUEST_CHANGES`.
- Blocking-scope instruction (opt-in per `## Blocking-scope verdict`): classify each Critical/High as in-diff (`+` lines) or out-of-diff; mark out-of-diff with `**Informational (out-of-diff):** `; emit `**Blocking Scope: NONE|OUT-OF-DIFF-ONLY|IN-DIFF**` before the footer. APPROVE/COMMENT rule unchanged.
- Ticket-context prelude (if Step 3 produced one).

### Step 5 — Parse decision footer + blocking-scope verdict

Scan ALL non-blank lines for the footer pattern:

```
^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$
```

Abort with "reviewer agent did not emit a valid Review Decision footer (APPROVE|COMMENT). Refusing to submit." if ANY of:
- Zero matches found.
- More than one matching line found.
- `REQUEST_CHANGES` appears anywhere in the agent output.

Do NOT clean up the worktree on abort — leave it for inspection.

Also scan for `^\*\*Blocking Scope:\s+(NONE|OUT-OF-DIFF-ONLY|IN-DIFF)\*\*$`; parse into `$BLOCKING_SCOPE`. Zero or >1 matches → `BLOCKING_SCOPE=IN-DIFF` (fail-safe). Log warning; do **not** abort — footer is the only hard-required contract.

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

3. Track counts: `posted=N`, `deduped=M`. Initialise `DEFERRED_INFORMATIONAL=""` before the loop. On HTTP 422: out-of-diff informational findings → `DEFERRED_INFORMATIONAL` (not stale-SHA; expected for context-line refs); in-diff findings on 422 → skip/log, stale-SHA counted.

### Step 7 — Submit + cleanup

Build the lean review body `$SUMMARY` — decision line + byline only. Findings are already posted as inline comments in Step 6; do NOT restate them here:

```bash
if [ -z "$CURRENT_USER" ] || [ -z "$AUTHOR_LOGIN" ]; then
  echo "[warn] IS_SELF_REVIEW: identity unknown (CURRENT_USER='$CURRENT_USER' AUTHOR_LOGIN='$AUTHOR_LOGIN'); treating as cross-author but diff-scoping flip suppressed (identity unknown)." >&2
  IS_SELF_REVIEW=false
elif [ "$CURRENT_USER" = "$AUTHOR_LOGIN" ]; then IS_SELF_REVIEW=true
else IS_SELF_REVIEW=false; fi

IDENTITY_KNOWN=$([ -n "$CURRENT_USER" ] && [ -n "$AUTHOR_LOGIN" ] && echo true || echo false)
if [ "$DECISION" = "COMMENT" ] && [ "$BLOCKING_SCOPE" = "OUT-OF-DIFF-ONLY" ] \
   && [ "$IS_SELF_REVIEW" = false ] && [ "$IDENTITY_KNOWN" = true ]; then
  DECISION=APPROVE
fi

BYLINE="_Reviewed by \`reviewer\` ([swe-workbench](https://github.com/lugassawan/swe-workbench)). Posted ${posted} inline comments, deduped ${deduped}._"
INFORMATIONAL_SECTION=""
[ -n "$DEFERRED_INFORMATIONAL" ] && INFORMATIONAL_SECTION=$(printf '\n\n### Informational (out-of-diff)\n\n%s\n' "$DEFERRED_INFORMATIONAL")
if [ "$IS_SELF_REVIEW" = false ]; then
  SUMMARY=$(printf '**Review Decision: %s**\n\n---\n%s%s\n' \
    "$DECISION" "$BYLINE" "$INFORMATIONAL_SECTION")
else
  SUMMARY=""
fi
```

Submit when `IS_SELF_REVIEW = false` (GitHub blocks self-approval):
- `APPROVE` → `gh pr review "$PR" --approve --body "$SUMMARY"`
- `COMMENT` → `gh pr review "$PR" --comment --body "$SUMMARY"`

Skip when `IS_SELF_REVIEW = true`. **Never** use `--request-changes`.

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

```bash
( rimba remove "pr-review-$PR" --force 2>/dev/null \
  || { git worktree remove --force "$WT" 2>/dev/null; \
       git branch -D "pr-review-$PR" 2>/dev/null; \
       bash "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/scripts/clean-ephemeral.sh" "$WT" 2>/dev/null; } ) &
```

## Footer parsing contract

- Regex: `^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$`
- Source: scan ALL non-blank lines of agent output.
- Abort cases (do NOT submit, preserve worktree):
  - Zero matches.
  - More than one matching line.
  - `REQUEST_CHANGES` appears anywhere in the agent output.

## Diff-scoping flip contract

Fires only when `DECISION=COMMENT` ∧ `BLOCKING_SCOPE=OUT-OF-DIFF-ONLY` ∧ `IS_SELF_REVIEW=false` ∧ `IDENTITY_KNOWN=true`. Self-review (AC#4): no flip when `IS_SELF_REVIEW=true`. Identity unknown: `IDENTITY_KNOWN=false` → no flip. Out-of-diff 422s → `DEFERRED_INFORMATIONAL` → `### Informational (out-of-diff)` in summary.

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
| Comment-post returns 422 (line out of range) | HTTP 422 | In-diff finding: skip, log "skipped (line out of range)", count toward stale-SHA. Out-of-diff informational: append to `DEFERRED_INFORMATIONAL`; do **not** count toward stale-SHA. |
| All in-diff POSTs returned 422 (stale `commit_id` — PR head advanced between Step 1 and Step 6) | `posted == 0` AND every **in-diff** finding skipped with 422 | Re-fetch `HEAD_SHA` via `gh pr view "$PR" --json headRefOid -q .headRefOid` and retry once. If still failing, abort with "HEAD_SHA mismatch — PR updated mid-review". Out-of-diff 422s do NOT trigger this path. |
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
| Emit the address-feedback CTA when there is nothing to address | The CTA is gated on outcome only: call `AskUserQuestion` when `DECISION = COMMENT` OR `posted > 0` OR `deduped > 0`. Suppress on clean approvals (APPROVE with `posted = 0` and `deduped = 0`). Self-review is NOT a suppression trigger. |
| Emit the CTA as plain text instead of `AskUserQuestion` | Always use the `AskUserQuestion` tool for the CTA — it gives the user a clickable button and eliminates the "type yes" friction. Never emit a free-text prompt asking the user to reply `yes`. |
| Apply the diff-scoping flip on self-review | The flip is gated on `IS_SELF_REVIEW = false`. A self-review with out-of-diff-only Critical/High findings stays `COMMENT`. |
| Fire the CTA after the diff-scoping flip when `DECISION=APPROVE`, `posted=0`, `deduped=0` | CTA suppression is evaluated post-flip. After a flip to `APPROVE`, `posted=0`, `deduped=0` → suppress. The informational findings land in the summary body (not inline threads); there is nothing for `/address-feedback` to act on. |
