---
name: workflow-address-feedback
description: Use when a PR owner wants to address review feedback — fetches outstanding threads, presents a per-thread triage (ADDRESSED / CLARIFIED / DEFERRED), applies fixes via the Edit tool, commits via workflow-commit-and-pr, posts per-thread replies via the GitHub comments API, and resolves addressed threads via GraphQL resolveReviewThread.
orchestrator: true
---

# Workflow: Address Feedback

**Announce at start:** "I'm using the workflow-address-feedback skill to address review feedback on PR #N."

## When to invoke

- The user runs `/swe-workbench:address-feedback <N>`.
- A PR owner wants to systematically work through review threads.
- Phrases: "address the feedback on PR 123", "help me resolve review comments", "triage and fix the review threads on #456".

## When NOT to invoke

- The reviewer side of the loop → use `swe-workbench:workflow-pr-review` or `swe-workbench:workflow-pr-review-followup`.
- The user just wants to reply to a single comment without the full triage flow.
- The PR is closed/merged.

## Composition

This skill orchestrates:
- `swe-workbench:ticket-context` — prepended context when PR references a ticket.
- `swe-workbench:workflow-commit-and-pr` — invoked after all ADDRESSED fixes are applied to commit and push.

## 5-phase flow

### Phase 1 — Pre-flight + fetch

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
[ -f "$_RT/runtime/clean-state-files.sh" ] || {
  echo "swe-workbench runtime scripts not found under $_RT/runtime — set CLAUDE_PLUGIN_ROOT and retry." >&2
  exit 1
}
JSON="/tmp/swe-workbench-address-feedback/${PR}.json"
eval "$("$_RT/runtime/preflight-pr.sh" "$PR" "$JSON")"
CURRENT_USER=$(gh api /user -q .login)
PR_BRANCH=$(jq -r .headRefName "$JSON")
```

`preflight-pr.sh` handles `gh auth status`, fetches the PR JSON to `$JSON`, and emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as shell assignments. `PR_BRANCH` is derived from `headRefName` in `$JSON` (address-feedback uses it for worktree setup in Phase 2).

Check that the PR is open before proceeding:
```bash
[ "$STATE" = "OPEN" ] || { echo "PR #$PR is $STATE — address-feedback only applies to open PRs."; exit 1; }
```

If `CURRENT_USER != AUTHOR_LOGIN`, warn:
> "You are not the PR author (PR author: @AUTHOR_LOGIN, you: @CURRENT_USER). Address-feedback flows are typically owner-side. Continue anyway? Reply `yes` to proceed."

Wait for confirmation before continuing.

Fetch outstanding review threads via GraphQL:

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
              }
            }
          }
        }
      }
    }
  }' > "/tmp/swe-workbench-address-feedback/${PR}-threads.json"
```

If all threads are resolved (or no threads exist), print:
> "No open threads — nothing to address."
Then exit cleanly.

If a prior triage save exists at `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, offer to resume from it.

### Phase 2 — Worktree

First, check whether the current branch already matches the PR head — if so, reuse the current worktree instead of creating a new one:

```bash
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" = "$PR_BRANCH" ] && [ "$CURRENT_BRANCH" != "HEAD" ]; then
  WT=$(pwd)
  REUSED_WT=1
  echo "Already on PR branch '$PR_BRANCH' — reusing the current worktree at $WT (skipping rimba add)."
  DIRTY=$(git status --porcelain)
  [ -n "$DIRTY" ] && echo "Note: working tree has uncommitted changes; the user may stash before Phase 4 commits to avoid sweeping unrelated edits into the feedback commit."
fi
```

If `$WT` is not yet set, check whether a worktree for `$PR_BRANCH` already exists elsewhere on disk (e.g. the session is on `main` but the branch was checked out previously):

```bash
if [ -z "$WT" ]; then
  EXISTING_WT=$(git worktree list --porcelain \
    | awk 'BEGIN{wt=""} /^worktree /{wt=$2} /^branch refs\/heads\/'"$PR_BRANCH"'/{print wt; exit}')
  if [ -n "$EXISTING_WT" ] && [ -d "$EXISTING_WT" ]; then
    WT="$EXISTING_WT"
    REUSED_WT=1
    echo "Found existing worktree for '$PR_BRANCH' at $WT (skipping rimba add)."
  fi
fi
```

If `$WT` is set by either check above, skip the rest of Phase 2 and proceed to Phase 3 — when the tree was dirty (first guard only), a non-blocking warning was already emitted; the user may stash before Phase 4 commits. Otherwise create a new durable worktree:

**When rimba is available** (preferred):

```bash
RIMBA_OUT=$(rimba add "pr:$PR" --task "address-feedback-$PR" --skip-deps --skip-hooks 2>&1)
WT=$(echo "$RIMBA_OUT" | awk '/Path:/{print $2}')
[ -d "$WT" ] || { echo "rimba add failed: $RIMBA_OUT"; exit 1; }
```

**When rimba is absent** (fallback):

```bash
WT="$HOME/.local/share/swe-workbench/address-feedback-${PR}"
mkdir -p "$(dirname "$WT")"
git fetch origin "${PR_BRANCH}"
git worktree add "$WT" "${PR_BRANCH}"
```

This worktree is **disposable** — fixes are committed and pushed to the PR branch in Phase 4, so the work lives on the remote, not the worktree. Phase 6 removes it on every exit (success, Q-quit, or error). If removal fails, a fallback is attempted; see Phase 6 for details. If the skill exits with an unrecoverable error at any point after this phase, run Phase 6 before stopping.

### Phase 3 — Triage digest

Render outstanding threads, one by one. **Filter out two kinds of thread before presenting:**

1. **Resolved threads** — skip any thread where `isResolved == true`.
2. **Already-clarified threads** — skip any *unresolved* thread where at least one *reply* comment (`comments.nodes[1:]` onwards — `nodes[0]` is the thread-opening comment, which in the typical reviewer-opened case belongs to the reviewer, not the PR owner) has `author.login` equal to `$CURRENT_USER`. This means the owner replied in a prior pass (e.g. a CLARIFIED reply) but left the thread unresolved. It applies whether that reply was posted by this skill or manually by the user. Detecting via reply comments only prevents false-positive skipping when the current user also authored review threads.

If any threads were skipped under rule 2, print a one-line transparency note before the digest:
> "(N thread(s) skipped — already clarified.)"

If no threads remain after filtering:
- When N ≥ 1 (threads were skipped under rule 2): print "No new threads to triage — N already clarified."
- When N = 0 (only resolved threads filtered): print "No new threads to triage."

Then run **Phase 6 — Cleanup** and exit cleanly.

For each remaining thread:

```
─────────────────────────────────────────────────
Thread #ID — {path}:{line}  by @{author}  [{Severity if parseable}]
─────────────────────────────────────────────────
> {first 200 chars of comment body}

[A]ddressed — fix + commit + reply + resolve
[C]larified — reply only (no resolve)
[D]eferred — skip this thread
[Q]uit — save progress and exit
```

Parse severity from `Severity: <level>` prefix in comment body if present; otherwise label `Unknown`.

Capture: `triage[<thread_id>] = A|C|D`.

If the owner replies `Q`, save triage state to `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, then run **Phase 6 — Cleanup**, and exit. Re-invocation resumes from this file (Phase 2 re-creates the worktree).

### Phase 4 — Implement + commit

For each `ADDRESSED` thread (in order):

1. Show the finding and the relevant file/line context.
2. Ask the owner for the fix approach (free-text). If the comment already contains a `### Suggested fix` block, offer to apply it automatically via the Edit tool.
3. Apply edits using the Edit tool.

After all `ADDRESSED` fixes are applied, invoke `swe-workbench:workflow-commit-and-pr` with the prompt:
> "commit and push these fixes addressing review feedback on PR #N"

This reuses the existing `[type]` commit format, branch-naming check, and push logic. After the skill returns, capture the resulting commit SHA:

```bash
FIX_SHA=$(git -C "$WT" rev-parse HEAD)
```

### Phase 5 — Reply + resolve

For each **ADDRESSED** or **CLARIFIED** thread, post a reply via REST then conditionally resolve (DEFERRED threads skip this call entirely). Use `comments.nodes[0].databaseId` (the thread root comment) as `$COMMENT_DATABASEID` — replies must target the first comment in the thread, not a subsequent reply.

Reply body templates by triage classification:
- **ADDRESSED**: `"Addressed in ${FIX_SHA}: <one-line summary of fix>."` — pass both `$REPLY_BODY` and `$THREAD_ID`.
- **CLARIFIED**: free-text owner-authored reply (asked interactively) — pass `$REPLY_BODY` with empty `$THREAD_ID` (reply only, no resolve).
- **DEFERRED**: pass empty `$REPLY_BODY` and empty `$THREAD_ID` (neither reply nor resolve).

```bash
bash "$_RT/runtime/reply-and-resolve.sh" \
  "$OWNER" "$REPO" "$PR" "$COMMENT_DATABASEID" "$THREAD_ID" "$REPLY_BODY"
```

After all replies and resolutions land, emit the follow-up CTA:

> "Want me to ping the reviewer to re-check? Reply `yes` to run `/review --check-followup <N>`."

On the Phase 5 success path, delete the address-feedback state files. The reap runs foreground; failures surface (no `2>/dev/null`):

```bash
bash "$_RT/runtime/clean-state-files.sh" \
  "/tmp/swe-workbench-address-feedback/${PR}.json" \
  "/tmp/swe-workbench-address-feedback/${PR}-threads.json" \
  "/tmp/swe-workbench-address-feedback/${PR}-triage.json"
for f in "/tmp/swe-workbench-address-feedback/${PR}.json" \
         "/tmp/swe-workbench-address-feedback/${PR}-threads.json" \
         "/tmp/swe-workbench-address-feedback/${PR}-triage.json"; do
  [ -e "$f" ] && echo "⚠ state file NOT reaped: $f" >&2 || echo "✓ state file reaped: $f"
done
```

Then run **Phase 6 — Cleanup**.

### Phase 6 — Cleanup (always)

Run on every exit that occurs after a worktree was **created** in Phase 2 (success, Q-quit, or error). Skip on Phase 1 early-exits (before any worktree exists) and when the reuse-guard fired (`REUSED_WT=1`) — the reuse path sets `$WT` to an existing checkout, never creates a worktree, so there is nothing to remove.

```bash
if [ "${REUSED_WT:-0}" = "1" ]; then
  echo "Reused existing worktree at $WT — skipping cleanup (nothing was created)."
else
  # positional arg matches the --task label set in Phase 2 ("address-feedback-$PR")
  if rimba remove "address-feedback-$PR" --force 2>/dev/null; then
    echo "Cleaned up worktree address-feedback-$PR."
  else
    # $WT is set in Phase 2 (both rimba and fallback paths); do not re-assign here
    git worktree remove --force "$WT" 2>/dev/null; bash "$_RT/runtime/clean-ephemeral.sh" "$WT" 2>/dev/null
    echo "⚠ rimba remove failed (rimba absent or worktree busy); attempted git-worktree fallback on $WT."
  fi
fi
```

Cleanup is **failure-tolerant**: if both rimba and the git fallback fail, log a warning and do not block completion. The fallback removes only the worktree directory — never delete `$PR_BRANCH` directly (e.g. via `git branch -D`), which would destroy the owner's actual PR head branch.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth` fails | Non-zero exit | Abort. |
| PR not found | `gh pr view` fails | Abort. |
| `CURRENT_USER != AUTHOR_LOGIN` | JSON mismatch | Warn + ask to continue. |
| No outstanding threads | GraphQL returns 0 unresolved | Print "No open threads — nothing to address." Exit. |
| Owner picks Q mid-triage | Loop exit | Save triage state to `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, run Phase 6 cleanup, then exit. |
| Worktree removal fails (rimba absent or busy) | `rimba remove` non-zero | Attempt `git worktree remove --force` fallback; log warning; do not block. |
| Reply REST fails (404 — comment deleted) | HTTP 404 | Skip that thread, log "skipped (comment deleted)". |
| Resolve mutation fails | GraphQL error | Reply already posted — log "reply posted but resolve failed". Continue. Do not roll back the reply. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Create a new worktree when already on the PR branch or when one already exists | Phase 2 runs two guards before `rimba add`: (1) compares `git rev-parse --abbrev-ref HEAD` against `$PR_BRANCH` — match reuses `$(pwd)`; (2) scans `git worktree list --porcelain` for a registered worktree on `$PR_BRANCH` — match reuses that path. Only fall through to creation when both checks find nothing. |
| Omit `--skip-deps --skip-hooks` on the rimba call | Always pass both flags — same as other worktree-creating skills. Deps can be installed manually in the worktree if needed. |
| Leave the worktree behind after skill exits | Phase 6 always removes it — skip Phase 6 only when exiting before Phase 2 (no worktree created yet) or when the reuse-guard fired (`REUSED_WT=1`, nothing was created). |
| Deleting `$PR_BRANCH` directly in Phase 6 fallback cleanup | Only remove the worktree directory — `$PR_BRANCH` is the real PR head branch; deleting it via `git branch -D` would destroy the owner's PR. |
| Post the reply before the commit | Always commit first (Phase 4) so `$FIX_SHA` is available for the ADDRESSED reply template. |
| Resolve a CLARIFIED thread | Only resolve ADDRESSED threads. CLARIFIED = reply only, no resolve. |
| Try to resolve via REST | Thread resolution is GraphQL-only (`resolveReviewThread` mutation). REST has no equivalent endpoint. |
| Re-present a thread the owner already clarified | On re-runs, skip *unresolved* threads that already have a comment authored by `$CURRENT_USER`. Detect via `comments.nodes[*].author.login`. |
