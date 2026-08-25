---
name: workflow-address-feedback
description: Use when a PR owner wants to address review feedback — fetches outstanding threads and general comments, presents a per-item triage (ADDRESSED / CLARIFIED / DEFERRED), applies fixes via the Edit tool, commits via workflow-commit-and-pr, posts replies via the GitHub API, resolves review threads via GraphQL resolveReviewThread (those without a thread are never resolved), and syncs stale PR metadata when drift is detected.
orchestrator: true
---

# Workflow: Address Feedback

**Announce at start:** "I'm using the workflow-address-feedback skill to address review feedback on PR #N."

## When to invoke

- The user runs `/swe-workbench:address-feedback <N>`.
- A PR owner wants to systematically work through review threads.
- Phrases: "address the feedback on PR 123", "help me resolve review comments", "triage and fix the review threads on #456".

## When NOT to invoke

- The reviewer side of the loop → use `swe-workbench:workflow-pr-review` (first-pass or followup mode).
- The user just wants to reply to a single comment without the full triage flow.
- The PR is closed/merged.

## Composition

This skill orchestrates:
- `swe-workbench:ticket-context` — prepended context when PR references a ticket.
- `swe-workbench:workflow-commit-and-pr` — invoked after all ADDRESSED fixes are applied to commit and push.

## Phase flow
### Phase 1 — Pre-flight + fetch
```bash
command -v swe-workbench-preflight-pr >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
JSON="/tmp/swe-workbench-address-feedback/${PR}.json"
eval "$(swe-workbench-preflight-pr "$PR" "$JSON")"
[ "$STATE" = "OPEN" ] || { swe-workbench-clean-state-files "$JSON"; echo "PR #$PR is $STATE — address-feedback only applies to open PRs."; exit 1; }
CURRENT_USER=$(gh api /user -q .login)
PR_BRANCH=$(jq -r .headRefName "$JSON"); RUN_DIR=$(swe-workbench-new-run-dir address-feedback "$PR")
```
`preflight-pr.sh` handles `gh auth status`, fetches the PR JSON to `$JSON`, and emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as shell assignments. The `[ "$STATE" = "OPEN" ]` gate runs immediately after the preflight fetch and before `$RUN_DIR` is allocated, so a rejected PR reaps `$JSON` inline via `swe-workbench-clean-state-files` rather than leaking it — `$RUN_DIR` never exists on this path, so there is nothing else to reap. `PR_BRANCH` is derived from `headRefName` in `$JSON` (address-feedback uses it for worktree setup in Phase 2). `new-run-dir.sh` allocates `$RUN_DIR` — a mode-0700 scratch directory under `/tmp/swe-workbench-run/` for this run's own ad-hoc bash artifacts, distinct from the deliberate PR-keyed state files below (including `${PR}-triage.json`, which is a cross-invocation resume point and must never move here).

If `CURRENT_USER != AUTHOR_LOGIN`, warn:
> "You are not the PR author (PR author: @AUTHOR_LOGIN, you: @CURRENT_USER). Address-feedback flows are typically owner-side. Continue anyway? Reply `yes` to proceed."

Wait for confirmation before continuing. If the user declines, run **Phase 7 — Cleanup** and exit.

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
Fetch PR-level conversation comments (general feedback on the main timeline, not a line comment) via REST, paginated (`--paginate` on this array endpoint emits one concatenated array per page, so `--jq '.[]' | jq -s '...'` flattens then re-wraps into one array); exclude bots and the owner (`$AUTHOR_LOGIN` or `$CURRENT_USER`, since this phase allows non-author runs — otherwise a non-author's own past replies would resurface as new triage items on every re-run), then flag `eligible: false` on reviewer comments already handled on a prior run — (a) an owner comment carries their `swe-workbench:handled:{id}` marker, or (b) an owner comment without any handled marker was posted after them (a manual reply); this dedup is lossy by construction, so Phase 3 always surfaces a transparency note instead of silently dropping:
```bash
gh api --paginate "repos/${OWNER}/${REPO}/issues/${PR}/comments" --jq '.[]' | jq -s \
  --arg author "$AUTHOR_LOGIN" --arg me "$CURRENT_USER" '
    (map(select((.user.login // "") == $author or (.user.login // "") == $me))) as $owner
    | map(select(((.user.type // "") != "Bot") and (((.user.login // "") | endswith("[bot]")) | not) and ((.user.login // "") != $author) and ((.user.login // "") != $me)))
    | map(. as $c
        | ($owner | any((.body // "") | contains("swe-workbench:handled:" + ($c.id | tostring) + " "))) as $marker
        | ($owner | any((((.body // "") | contains("swe-workbench:handled")) | not) and (.created_at > $c.created_at))) as $manual
        | $c + {eligible: (($marker or $manual) | not)})
  ' > "/tmp/swe-workbench-address-feedback/${PR}-pr-comments.json"
ELIGIBLE_PR_COMMENTS=$(jq '[.[] | select(.eligible)] | length' "/tmp/swe-workbench-address-feedback/${PR}-pr-comments.json")
SKIPPED_PR_COMMENTS=$(jq '[.[] | select(.eligible | not)] | length' "/tmp/swe-workbench-address-feedback/${PR}-pr-comments.json")
```
If all threads are resolved (or no threads exist) **and** `$ELIGIBLE_PR_COMMENTS` is zero, print:
> "No open threads — nothing to address."
Then run **Phase 7 — Cleanup** and exit.

If a prior triage save exists at `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, offer to resume from it.

### Phase 2 — Worktree

First refresh the remote ref — run `git fetch origin "$PR_BRANCH" || echo "⚠ fetch of $PR_BRANCH failed — fork PR? see Failure modes"` — every path below (the guards' reconcile, the create block's `--source`) needs a current `origin/$PR_BRANCH`. Then check whether the current branch already matches the PR head — if so, reuse the current worktree instead of creating a new one:
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
    | awk -v b="refs/heads/$PR_BRANCH" 'BEGIN{wt=""} /^worktree /{wt=$2} $0 == "branch " b {print wt; exit}')
  if [ -n "$EXISTING_WT" ] && [ -d "$EXISTING_WT" ]; then
    WT="$EXISTING_WT"
    REUSED_WT=1
    echo "Found existing worktree for '$PR_BRANCH' at $WT (skipping rimba add)."
  fi
fi
```
If `$WT` is set by either check above, skip the create block below, run the shared reconcile block after it, then proceed to Phase 3 — when the tree was dirty (first guard only), a non-blocking warning was already emitted; the user may stash before Phase 4 commits. Otherwise create a new durable worktree **on the PR branch itself** (`$PR_BRANCH`), so commits pushed in Phase 4 update the PR directly (`git push -u origin "$PR_BRANCH"` — never a throwaway task branch):

```bash
WT=""
if command -v rimba >/dev/null 2>&1; then
  if git show-ref --verify --quiet "refs/heads/$PR_BRANCH"; then
    # Local branch exists (kept by a prior run's Phase 7) — checkout preserves unpushed crash-recovery commits.
    WT="$HOME/.local/share/swe-workbench/address-feedback-${PR}"
    git worktree add "$WT" "$PR_BRANCH" || WT=""
  else
    RIMBA_OUT=$(rimba add "$PR_BRANCH" --source "origin/$PR_BRANCH" 2>&1)
    WT=$(printf '%s\n' "$RIMBA_OUT" | awk '/Path:/{print $2}')
    if [ -n "$WT" ] && [ -d "$WT" ]; then
      WT_BRANCH=$(git -C "$WT" rev-parse --abbrev-ref HEAD)
      if [ "$WT_BRANCH" != "$PR_BRANCH" ]; then
        # rimba re-prefixed a non-conventional name (feature/<name>) — wrong branch; tear down and fall through to git.
        rimba remove "$WT_BRANCH" --force >/dev/null 2>&1; git worktree remove --force "$WT" >/dev/null 2>&1; WT=""
      fi
    else
      echo "rimba add failed: $RIMBA_OUT"; WT=""
    fi
  fi
fi
if [ -z "$WT" ]; then  # rimba absent/failed/re-prefixed; || covers a local branch existing after teardown
  WT="$HOME/.local/share/swe-workbench/address-feedback-${PR}"
  git worktree add -b "$PR_BRANCH" "$WT" "origin/$PR_BRANCH" 2>/dev/null || git worktree add "$WT" "$PR_BRANCH"
fi
[ -e "$WT/.git" ] || { echo "worktree creation failed at $WT"; exit 1; }
```

Shared reconcile for **every** Phase 2 path (reused crash-leftovers go stale; fresh creates are no-ops):
```bash
if [ -n "$WT" ] && git merge-base --is-ancestor "$PR_BRANCH" "origin/$PR_BRANCH"; then git -C "$WT" merge --ff-only "origin/$PR_BRANCH" >/dev/null 2>&1 || echo "⚠ fast-forward of $PR_BRANCH failed"; fi
[ -n "$WT" ] && git show-ref --verify --quiet "refs/remotes/origin/$PR_BRANCH" && ! git merge-base --is-ancestor "origin/$PR_BRANCH" "$PR_BRANCH" && echo "⚠ local $PR_BRANCH diverged from origin/$PR_BRANCH — rebase before Phase 4."
command -v rimba >/dev/null 2>&1 && rimba deps install "$PR_BRANCH" || echo "⚠ rimba deps install failed — install deps manually before running tests."
```

No `--skip-deps`/`--skip-hooks` anywhere on the create path — rimba installs dependencies and runs `post_create` hooks so the worktree is fully initialized with no separate repository-specific bootstrap step. Wait for `rimba add` to complete before running tests in the worktree.

This worktree is **disposable but sits on the PR branch itself** — Phase 4 commits and pushes from it update the PR directly, so the work lives on the PR branch, not a throwaway task branch. Phase 7 removes the worktree on every exit (success, Q-quit, or error) but **keeps the local `$PR_BRANCH`**: it is the owner's actual PR head branch, and keeping it preserves unpushed commits if a prior run crashed mid-Phase-4 (the next run checks that branch out instead of re-creating it). Never delete `$PR_BRANCH` (e.g. via `git branch -D`). If removal fails, a fallback is attempted; see Phase 7 for details. If the skill exits with an unrecoverable error at any point after this phase, run Phase 7 before stopping.

### Phase 3 — Triage digest

Render outstanding threads and eligible PR-level conversation comments, one by one. **Filter out before presenting:**

1. **Resolved threads** — skip any thread where `isResolved == true`.
2. **Already-clarified threads** — skip any *unresolved* thread where at least one *reply* comment (`comments.nodes[1:]` onwards — `nodes[0]` is the thread-opening comment, which in the typical reviewer-opened case belongs to the reviewer, not the PR owner) has `author.login` equal to `$CURRENT_USER`. This means the owner replied in a prior pass (e.g. a CLARIFIED reply) but left the thread unresolved. It applies whether that reply was posted by this skill or manually by the user. Detecting via reply comments only prevents false-positive skipping when the current user also authored review threads.
3. **Already-handled PR comments** — bot/tool comments and the owner's own comments never made it into `${PR}-pr-comments.json` (dropped in Phase 1); entries that did but carry `eligible == false` were deduped there (already marker-replied or manually replied to on a prior run). Only `eligible == true` entries are presented.

If any threads or PR comments were skipped (rule 2 / rule 3), print transparency notes before the digest:
> "(N thread(s) skipped — already clarified.)"
> "(N PR comment(s) skipped — already handled.)"

If no threads and no eligible PR comments (`$ELIGIBLE_PR_COMMENTS == 0`) remain after filtering:
- When any items were skipped under rule 2 or rule 3: print "No new items to triage — N already clarified/handled."
- When nothing was skipped (only resolved threads filtered, and no PR comments existed): print "No new items to triage."

Then run **Phase 7 — Cleanup** and exit cleanly.

For each remaining thread:
```
─────────────────────────────────────────────────
Thread #ID — {path}:{line}  by @{author}  [{Severity if parseable}]
─────────────────────────────────────────────────
> {first 200 chars of comment body}

[A]ddressed — fix + commit + reply + resolve
[C]larified — reply + resolve
[D]eferred — reply + resolve (acknowledged, not fixed now)
[Q]uit — save progress and exit
```
Parse severity from `Severity: <level>` prefix in comment body if present; otherwise label `Unknown`.

Capture: `triage[<thread_id>] = A|C|D`.

For each remaining PR comment (no `path:line`, no resolve state), key as `triage["prcomment:<comment.id>"]` (namespaced against review-thread node IDs in the same flat map; carries the id needed for the Phase 5 marker; both key kinds round-trip through Q-quit save/resume unchanged):
```
PR comment by @{author}
> {first 200 chars of comment body}

[A]ddressed — fix + commit + reply (PR comments have no thread to resolve)
[C]larified — reply only
[D]eferred — skip this comment
[Q]uit — save progress and exit
```
If the owner replies `Q` at any point in either loop, save triage state to `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, then run **Phase 7 — Cleanup**, and exit. Re-invocation resumes from this file (Phase 2 re-creates the worktree).

### Phase 4 — Implement + commit

For each `ADDRESSED` review thread or PR comment (in order — both sources share this loop, since the commit step is source-agnostic):

1. Show the finding and the relevant file/line context (PR comments have no `path:line`; show the comment body instead).
2. Ask the owner for the fix approach (free-text). If the comment already contains a `### Suggested fix` block, offer to apply it automatically via the Edit tool.
3. Apply edits using the Edit tool.

After all `ADDRESSED` fixes are applied, invoke `swe-workbench:workflow-commit-and-pr` with the prompt:
> "commit and push these fixes addressing review feedback on PR #N"

This reuses the existing `[type]` commit format, branch-naming check, and push logic. After the skill returns, capture the resulting commit SHA:
```bash
FIX_SHA=$(git -C "$WT" rev-parse HEAD)
```

### Phase 5 — Reply + resolve

For each **ADDRESSED**, **CLARIFIED**, or **DEFERRED** review thread, post a reply via REST then resolve via GraphQL `resolveReviewThread` by calling `swe-workbench-reply-and-resolve` with the triage-mapped args — all three dispositions now resolve the thread, since an open thread blocks `/swe-workbench:review`'s approval gate regardless of *why* it was left open. For each **ADDRESSED** or **CLARIFIED** PR comment, post a reply via REST — PR comments have no thread, so resolve is always suppressed and `KIND=issue` is passed explicitly, with a hidden `swe-workbench:handled:{id}` marker embedded in the reply body for Phase 1's re-run dedup; DEFERRED PR comments are skipped entirely, unchanged. Reply targets the thread root comment (`comments.nodes[0].databaseId`), never a subsequent reply. Full reply-body templates, exact invocation args, and the PR-comment quoting/escaping caveat live in `reference/resolve-review-threads.md`.

After all replies and resolutions land, emit the follow-up CTA:

> "Want me to ping the reviewer to re-check? Reply `yes` to run `/swe-workbench:review --check-followup <N>`."

On the Phase 5 success path, delete the triage resume-point file. The three run-scoped state files (`${PR}.json`, `${PR}-threads.json`, `${PR}-pr-comments.json`) are reaped by **Phase 7** on every exit instead — `${PR}-triage.json` is reaped here specifically, because completion is what makes the resume point spent, and Phase 7 must never touch it (see Phase 7). The reap runs foreground; failures surface (no `2>/dev/null`):
```bash
swe-workbench-clean-state-files "/tmp/swe-workbench-address-feedback/${PR}-triage.json"
[ -e "/tmp/swe-workbench-address-feedback/${PR}-triage.json" ] \
  && echo "⚠ state file NOT reaped: /tmp/swe-workbench-address-feedback/${PR}-triage.json" >&2 \
  || echo "✓ state file reaped: /tmp/swe-workbench-address-feedback/${PR}-triage.json"
```
Then run **Phase 6 — Sync PR metadata**.

### Phase 6 — Sync PR metadata (when fixes were committed)

Skipped when `$FIX_SHA` is unset (no fixes committed in Phase 4). Otherwise fetches the live PR title/body, commit subjects, and diff stat, judges drift against the title and `## Summary` section, and — on detected drift, after a `Reply \`yes\`` preview gate — applies a revised title/summary via `swe-workbench-sync-pr-metadata` while preserving `## Test Plan`, the `Closes #`/`Fixes #`/`Issue: N/A` trailer, and all other sections. Full fetch commands, drift-judging criteria, and apply mechanics live in `reference/sync-pr-metadata.md`. Then run **Phase 7 — Cleanup**.

### Phase 7 — Cleanup (always)

Run on every exit after the Phase 1 preflight line. Skip the worktree-removal block on Phase 1 early-exits (before any worktree exists) and when the reuse-guard fired (`REUSED_WT=1`) — the reuse path sets `$WT` to an existing checkout, never creates a worktree, so there is nothing to remove. The `${WT:-}` check specifically guards against a Phase-1-only exit falling into the `rimba remove "$PR_BRANCH"` branch below: that command is keyed by branch name alone, not by this run's own `$WT`, so without the guard it could force-remove a different, concurrently-active session's live worktree on the same PR branch.
```bash
if [ -z "${WT:-}" ]; then
  echo "No worktree was created this run — skipping worktree cleanup."
elif [ "${REUSED_WT:-0}" = "1" ]; then
  echo "Reused existing worktree at $WT — skipping cleanup (nothing was created)."
else
  # task = the PR branch (Phase 2 creates the worktree on $PR_BRANCH); --keep-branch
  # preserves the local PR head branch — rimba remove deletes the branch without it.
  if rimba remove "$PR_BRANCH" --force --keep-branch 2>/dev/null; then
    echo "Cleaned up worktree for $PR_BRANCH (local branch kept)."
  else
    # $WT is set in Phase 2 (both rimba and fallback paths); do not re-assign here
    git worktree remove --force "$WT" 2>/dev/null; swe-workbench-clean-ephemeral "$WT" 2>/dev/null
    echo "⚠ rimba remove failed (rimba absent or worktree busy); attempted git-worktree fallback on $WT."
  fi
fi
[ -n "${RUN_DIR:-}" ] && { swe-workbench-reap-run-dir "$RUN_DIR"; [ -e "$RUN_DIR" ] && echo "⚠ run dir NOT reaped: $RUN_DIR" >&2 || echo "✓ run dir reaped: $RUN_DIR"; }
swe-workbench-clean-state-files \
  "/tmp/swe-workbench-address-feedback/${PR}.json" \
  "/tmp/swe-workbench-address-feedback/${PR}-threads.json" \
  "/tmp/swe-workbench-address-feedback/${PR}-pr-comments.json"
for f in "/tmp/swe-workbench-address-feedback/${PR}.json" \
         "/tmp/swe-workbench-address-feedback/${PR}-threads.json" \
         "/tmp/swe-workbench-address-feedback/${PR}-pr-comments.json"; do
  [ -e "$f" ] && echo "⚠ state file NOT reaped: $f" >&2 || echo "✓ state file reaped: $f"
done
```
Cleanup is **failure-tolerant**: if both rimba and the git fallback fail, log a warning and do not block completion. The fallback removes only the worktree directory — never delete `$PR_BRANCH` directly (e.g. via `git branch -D`), which would destroy the owner's actual PR head branch. `$RUN_DIR` is reaped unconditionally whenever it exists, independent of the `REUSED_WT` branch above — it was allocated in Phase 1 regardless of whether Phase 2 later reused an existing worktree. It is guarded with `${RUN_DIR:-}` because the Phase 1 `STATE`-gate rejection is the one exit that precedes `$RUN_DIR`'s allocation entirely — that path reaps `$JSON` inline instead of routing through this phase (see Phase 1) and never reaches this guard. The three run-scoped state files reaped above (`${PR}.json`, `${PR}-threads.json`, `${PR}-pr-comments.json`) are the ones whose lifetime ends with the run itself; the resume-point file created on Q-quit is reaped separately, on completion, in Phase 5 — never here, since a Q-quit into this phase must leave it intact for the next invocation to resume from.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth` fails | Non-zero exit | Abort. |
| PR not found | `gh pr view` fails | Abort. |
| `CURRENT_USER != AUTHOR_LOGIN` | JSON mismatch | Warn + ask to continue. |
| No outstanding threads | GraphQL returns 0 unresolved | Print "No open threads — nothing to address." Exit. |
| Owner picks Q mid-triage | Loop exit | Save triage state to `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, run Phase 7 cleanup, then exit. |
| Worktree removal fails (rimba absent or busy) | `rimba remove` non-zero | Attempt `git worktree remove --force` fallback; log warning; do not block. |
| Reply REST fails (404 — comment deleted) | HTTP 404 | Skip that thread, log "skipped (comment deleted)". |
| Resolve mutation fails | GraphQL error | Reply already posted — log "reply posted but resolve failed". Continue. Do not roll back the reply. |
| rimba re-prefixes a non-conventional PR branch name (worktree on `feature/<name>` ≠ `$PR_BRANCH`) | Post-create branch verification mismatch | Remove the mis-branched worktree, fall back to `git worktree add -b "$PR_BRANCH" … "origin/$PR_BRANCH"`. |
| Fork PR — branch exists only on the fork remote | `git fetch origin "$PR_BRANCH"` fails / `origin/$PR_BRANCH` missing | Out of scope: add the fork remote manually (`git remote add gh-fork-<owner> …`) and check out the PR head by hand, then re-run. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Create a new worktree when already on the PR branch or when one already exists | Phase 2 runs two guards before `rimba add`: (1) compares `git rev-parse --abbrev-ref HEAD` against `$PR_BRANCH` — match reuses `$(pwd)`; (2) scans `git worktree list --porcelain` for a registered worktree on `$PR_BRANCH` — match reuses that path. Only fall through to creation when both checks find nothing. |
| Pass `--skip-deps --skip-hooks` on the Phase 2 create | Never pass either flag — rimba must install deps and run hooks so the worktree is fully initialized with no separate bootstrap step. |
| Create the worktree on a throwaway task branch (`rimba add pr:$PR --task …`) | Use `rimba add "$PR_BRANCH" --source "origin/$PR_BRANCH"` so the worktree is on the PR branch itself — Phase 4 pushes update the PR directly. |
| Leave the worktree behind after skill exits | Phase 7 runs on every exit past the Phase 1 preflight line — including exits before Phase 2 ever ran — but its worktree-removal block only fires when `$WT` is actually set; a Phase 1 early exit (`$WT` unset) or the reuse-guard (`REUSED_WT=1`) both skip removal since there is nothing this run created. |
| Deleting `$PR_BRANCH` directly in Phase 7 fallback cleanup | Only remove the worktree directory — `$PR_BRANCH` is the real PR head branch; deleting it via `git branch -D` would destroy the owner's PR. |
| Post the reply before the commit | Always commit first (Phase 4) so `$FIX_SHA` is available for the ADDRESSED reply template. |
| Leave a CLARIFIED/DEFERRED **thread** open after reply | All three review-thread dispositions now resolve — an open thread blocks `/swe-workbench:review`'s approval gate. PR comments are unaffected (no thread to resolve). |
| Try to resolve via REST | Thread resolution is GraphQL-only (`resolveReviewThread` mutation). REST has no equivalent endpoint. |
| Re-present a thread the owner already clarified | On re-runs, skip *unresolved* threads that already have a comment authored by `$CURRENT_USER`. Detect via `comments.nodes[*].author.login`. |
