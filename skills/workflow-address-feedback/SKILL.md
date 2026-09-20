---
name: workflow-address-feedback
description: Use when a PR owner wants to address review feedback — fetches outstanding threads and general comments, presents a per-item triage (ADDRESSED / CLARIFIED / DEFERRED), applies fixes via the Edit tool, commits via workflow-commit-and-pr, resolves review threads via GraphQL resolveReviewThread (those without a thread are never resolved), and syncs stale PR metadata when drift is detected.
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
command -v swe-workbench-address-feedback-fetch >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
RESULT=$(swe-workbench-address-feedback-fetch --pr "$PR" \
  | swe-workbench-result-check swb.address-feedback-fetch/1) || exit 1
STATE=$(printf '%s' "$RESULT" | jq -r '.data.state')
JSON=$(printf '%s' "$RESULT" | jq -r '.data.pr_json_path')
[ "$STATE" = "OPEN" ] || { swe-workbench-clean-state-files "$JSON"; echo "PR #$PR is $STATE — address-feedback only applies to open PRs."; exit 1; }
OWNER=$(printf '%s' "$RESULT" | jq -r '.data.owner')
REPO=$(printf '%s' "$RESULT" | jq -r '.data.repo')
AUTHOR_LOGIN=$(printf '%s' "$RESULT" | jq -r '.data.author_login')
CURRENT_USER=$(printf '%s' "$RESULT" | jq -r '.data.current_user')
PR_BRANCH=$(printf '%s' "$RESULT" | jq -r '.data.pr_branch')
THREADS_PATH=$(printf '%s' "$RESULT" | jq -r '.data.threads_path')
PR_COMMENTS_PATH=$(printf '%s' "$RESULT" | jq -r '.data.pr_comments_path')
TRIAGE_PATH=$(printf '%s' "$RESULT" | jq -r '.data.triage_path')
RESUME_TRIAGE_PATH=$(printf '%s' "$RESULT" | jq -r '.data.resume_triage_path')
ELIGIBLE_THREADS=$(printf '%s' "$RESULT" | jq -r '.data.eligible_threads')
SKIPPED_THREADS_CLARIFIED=$(printf '%s' "$RESULT" | jq -r '.data.skipped_threads_clarified')
ELIGIBLE_PR_COMMENTS=$(printf '%s' "$RESULT" | jq -r '.data.eligible_pr_comments')
SKIPPED_PR_COMMENTS=$(printf '%s' "$RESULT" | jq -r '.data.skipped_pr_comments')
RUN_DIR=$(swe-workbench-new-run-dir address-feedback "$PR")
```
`swe-workbench-address-feedback-fetch` handles `gh auth status`, fetches the PR JSON to `$JSON` (via `swe-workbench-preflight-pr`), and — when the PR is OPEN — paginates review threads and PR-level conversation comments, projecting `eligible`/`skip_reason` onto each entry (resolved/already-clarified for threads; bot/owner/marker/manual-reply exclusion for PR comments) before writing them to `$THREADS_PATH`/`$PR_COMMENTS_PATH`. The `[ "$STATE" = "OPEN" ]` gate runs immediately after the fetch and before `$RUN_DIR` is allocated, so a rejected PR reaps `$JSON` inline via `swe-workbench-clean-state-files` rather than leaking it — `$RUN_DIR` never exists on this path, so there is nothing else to reap. `new-run-dir.sh` allocates `$RUN_DIR` — a mode-0700 scratch directory under `/tmp/swe-workbench-run/` for this run's own ad-hoc bash artifacts, distinct from the deliberate PR-keyed state files above (including `$TRIAGE_PATH`, which is a cross-invocation resume point and must never move here). All four state paths are repo-scoped: the fetch resolves the owner-repo slug itself — explicit `--repo` when the invocation carried a full PR URL, else the checkout's origin remote, else legacy un-scoped names — so same-numbered PRs in different repositories never collide.

If `CURRENT_USER != AUTHOR_LOGIN`, warn:
> "You are not the PR author (PR author: @AUTHOR_LOGIN, you: @CURRENT_USER). Address-feedback flows are typically owner-side. Continue anyway? Reply `yes` to proceed."

Wait for confirmation before continuing. If the user declines, run **Phase 7 — Cleanup** and exit.

If `$ELIGIBLE_THREADS` and `$ELIGIBLE_PR_COMMENTS` are both zero, nothing is left to triage — one merged check, replacing two separate early-exits the pre-runtime-command version had (this now runs before Phase 2 ever spins up a worktree, unlike before):
- `$SKIPPED_THREADS_CLARIFIED` or `$SKIPPED_PR_COMMENTS` is non-zero: print "No new items to triage — N already clarified/handled." (`N` = their sum).
- Otherwise, when some threads existed but were all resolved (nothing was skipped as already-clarified/-handled): print "No new items to triage."
- Otherwise, when `$ELIGIBLE_PR_COMMENTS` is zero and no threads existed at all (`jq 'length' "$THREADS_PATH"` is zero): print "No open threads — nothing to address."

Then run **Phase 7 — Cleanup** and exit.

If the envelope's `resume_available` is true, offer to resume — reading the saved decisions from `$RESUME_TRIAGE_PATH`, which the fetch resolves to wherever the data actually lives (the scoped `$TRIAGE_PATH`, or a pre-upgrade session's legacy un-scoped `/tmp/swe-workbench-address-feedback/${PR}-triage.json`, dual-read). New saves always go to `$TRIAGE_PATH`, so a resumed session migrates to the scoped spelling on its next save.

### Phase 2 — Worktree

Acquire the worktree via the runtime command — it owns the reuse-current / reuse-existing / create-via-rimba / create-via-git decision, the `origin/$PR_BRANCH` fetch, the fast-forward-or-diverged-warn reconcile, and `rimba deps install`:
```bash
RESULT=$(swe-workbench-address-feedback-worktree acquire --pr "$PR" --branch "$PR_BRANCH" \
  | swe-workbench-result-check swb.address-feedback-worktree-acquire/1) || exit 1
WT=$(printf '%s' "$RESULT" | jq -r '.data.path')
CREATED_WT=$(printf '%s' "$RESULT" | jq -r 'if .data.reused then "false" else "true" end')
printf '%s' "$RESULT" | jq -r '
  if .data.reused then "Reusing worktree (" + .data.reuse_reason + ") at " + .data.path
  else "Created worktree at " + .data.path end'
[ "$(printf '%s' "$RESULT" | jq -r '.data.dirty')" = "true" ] && \
  echo "Note: working tree has uncommitted changes; the user may stash before Phase 4 commits to avoid sweeping unrelated edits into the feedback commit."
[ "$(printf '%s' "$RESULT" | jq -r '.status')" = "partial" ] && \
  printf '%s' "$RESULT" | jq -r '.warnings[] | "⚠ " + .message'
```

This worktree is **disposable but sits on the PR branch itself** — Phase 4 commits and pushes from it update the PR directly, so the work lives on the PR branch, not a throwaway task branch. Phase 7 removes the worktree on every exit (success, Q-quit, or error) but **keeps the local `$PR_BRANCH`**: it is the owner's actual PR head branch, and keeping it preserves unpushed commits if a prior run crashed mid-Phase-4 (the next run's `acquire` checks that branch out instead of re-creating it). Never delete `$PR_BRANCH` (e.g. via `git branch -D`) — `swe-workbench-address-feedback-worktree release` never issues one. If the skill exits with an unrecoverable error at any point after this phase, run Phase 7 before stopping.

### Phase 3 — Triage digest

Read `$THREADS_PATH` and `$PR_COMMENTS_PATH` (`jq '[.[] | select(.eligible)]'` on each) and render only the `eligible == true` entries, one by one — the fetch command already applied the resolved/already-clarified exclusion for threads and the bot/owner/marker/manual-reply exclusion for PR comments, so Phase 3 never re-implements those rules itself.

If `$SKIPPED_THREADS_CLARIFIED` or `$SKIPPED_PR_COMMENTS` is non-zero, print transparency notes before the digest — this dedup is lossy by construction, so a transparency note replaces silently dropping:
> "(N thread(s) skipped — already clarified.)"
> "(N PR comment(s) skipped — already handled.)"

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
If the owner replies `Q` at any point in either loop, save triage state to `$TRIAGE_PATH`, then run **Phase 7 — Cleanup**, and exit. Re-invocation resumes from this file (Phase 2 re-creates the worktree).

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

On the Phase 5 success path, delete the triage resume-point file. The three run-scoped state files (`$JSON`, `$THREADS_PATH`, `$PR_COMMENTS_PATH` — repo-scoped per) are reaped by **Phase 7** on every exit instead — `$TRIAGE_PATH` is reaped here specifically, because completion is what makes the resume point spent, and Phase 7 must never touch it (see Phase 7). The reap runs foreground; failures surface (no `2>/dev/null`):
```bash
swe-workbench-clean-state-files "$TRIAGE_PATH"
[ -e "$TRIAGE_PATH" ] \
  && echo "⚠ state file NOT reaped: $TRIAGE_PATH" >&2 \
  || echo "✓ state file reaped: $TRIAGE_PATH"
```
Then run **Phase 6 — Sync PR metadata**.

### Phase 6 — Sync PR metadata (when fixes were committed)

Skipped when `$FIX_SHA` is unset (no fixes committed in Phase 4). Otherwise fetches the live PR title/body, commit subjects, and diff stat, judges drift against the title and `## Summary` section, and — on detected drift, after a `Reply \`yes\`` preview gate — applies a revised title/summary via `swe-workbench-sync-pr-metadata` while preserving `## Test Plan`, the `Closes #`/`Fixes #`/`Issue: N/A` trailer, and all other sections. Full fetch commands, drift-judging criteria, and apply mechanics live in `reference/sync-pr-metadata.md`. Then run **Phase 7 — Cleanup**.

### Phase 7 — Cleanup (always)

Run on every exit after the Phase 1 preflight line. Skip the worktree-removal block on Phase 1 early-exits (before any worktree exists) — `$WT` is unset there since Phase 2 never ran. Otherwise call `release`, which itself no-ops when `$CREATED_WT` is `"false"` (a reused worktree was never created, so there is nothing for it to remove) — the runtime command's own `--created` flag carries that distinction now, replacing the old skill-level `REUSED_WT` variable.
```bash
if [ -z "${WT:-}" ]; then
  echo "No worktree was created this run — skipping worktree cleanup."
else
  RELEASE_RESULT=$(swe-workbench-address-feedback-worktree release \
    --pr "$PR" --path "$WT" --branch "$PR_BRANCH" --created "$CREATED_WT" \
    | swe-workbench-result-check swb.address-feedback-worktree-release/1) || RELEASE_RESULT=""
  if [ -z "$RELEASE_RESULT" ]; then
    echo "⚠ swe-workbench-address-feedback-worktree release failed — worktree at $WT may need manual cleanup."
  elif [ "$(printf '%s' "$RELEASE_RESULT" | jq -r '.data.removed')" = "true" ]; then
    echo "Cleaned up worktree at $WT (local branch kept)."
  elif [ "$(printf '%s' "$RELEASE_RESULT" | jq -r '.status')" = "ok" ]; then
    echo "Reused existing worktree at $WT — skipping cleanup (nothing was created)."
  else
    echo "⚠ release did not remove $WT — see warnings below."
    printf '%s' "$RELEASE_RESULT" | jq -r '.warnings[] | "⚠ " + .message'
  fi
fi
[ -n "${RUN_DIR:-}" ] && { swe-workbench-reap-run-dir "$RUN_DIR"; [ -e "$RUN_DIR" ] && echo "⚠ run dir NOT reaped: $RUN_DIR" >&2 || echo "✓ run dir reaped: $RUN_DIR"; }
swe-workbench-clean-state-files "$JSON" "$THREADS_PATH" "$PR_COMMENTS_PATH"
for f in "$JSON" "$THREADS_PATH" "$PR_COMMENTS_PATH"; do
  [ -e "$f" ] && echo "⚠ state file NOT reaped: $f" >&2 || echo "✓ state file reaped: $f"
done
```
Cleanup is **failure-tolerant**: `release` always exits 0, and a genuine removal failure surfaces as a warning rather than blocking completion. `release` is path-keyed and never issues a branch-deleting command, so `$PR_BRANCH` — the owner's actual PR head branch — can never be destroyed by this step. `$RUN_DIR` is reaped unconditionally whenever it exists, independent of whether Phase 2 reused an existing worktree. It is guarded with `${RUN_DIR:-}` because the Phase 1 `STATE`-gate rejection is the one exit that precedes `$RUN_DIR`'s allocation entirely — that path reaps `$JSON` inline instead of routing through this phase (see Phase 1) and never reaches this guard. `$JSON`/`$THREADS_PATH`/`$PR_COMMENTS_PATH` are the paths the Phase 1 fetch envelope named — reaping whatever the manifest names, rather than re-hardcoding the three literals, keeps this list and `swe-workbench-address-feedback-fetch`'s own output in permanent sync. These are the state files whose lifetime ends with the run itself; the resume-point file created on Q-quit is reaped separately, on completion, in Phase 5 — never here, since a Q-quit into this phase must leave it intact for the next invocation to resume from.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth` fails | Non-zero exit | Abort. |
| PR not found | `gh pr view` fails | Abort. |
| `CURRENT_USER != AUTHOR_LOGIN` | JSON mismatch | Warn + ask to continue. |
| No outstanding threads | GraphQL returns 0 unresolved | Print "No open threads — nothing to address." Exit. |
| Owner picks Q mid-triage | Loop exit | Save triage state to `$TRIAGE_PATH`, run Phase 7 cleanup, then exit. |
| Worktree removal fails | `release`'s `data.removed` is `false` | `release` still exits 0 with `status: "partial"` and a `warnings` entry — log it; do not block. |
| Reply REST fails (404 — comment deleted) | HTTP 404 | Skip that thread, log "skipped (comment deleted)". |
| Resolve mutation fails | GraphQL error | Reply already posted — log "reply posted but resolve failed". Continue. Do not roll back the reply. |
| rimba re-prefixes a non-conventional PR branch name (worktree on `feature/<name>` ≠ `$PR_BRANCH`) | `acquire`'s post-create branch verification mismatch | Handled internally by `acquire`: removes the mis-branched worktree and falls back to a plain `git worktree add`. |
| Fork PR — branch exists only on the fork remote | `git fetch origin "$PR_BRANCH"` fails / `origin/$PR_BRANCH` missing | Out of scope: add the fork remote manually (`git remote add gh-fork-<owner> …`) and check out the PR head by hand, then re-run. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Create a new worktree when already on the PR branch or when one already exists | `acquire` runs the reuse-current and reuse-existing checks internally before ever creating anything — Phase 2 never needs to reimplement them. |
| Re-implement `--skip-deps`/`--skip-hooks` handling in Phase 2 | `acquire` never exposes either flag — it always installs deps so the worktree is fully initialized with no separate bootstrap step. |
| Create the worktree on a throwaway task branch | `acquire` always creates on `$PR_BRANCH` itself, never a throwaway task branch — Phase 4 pushes update the PR directly. |
| Leave the worktree behind after skill exits | Phase 7 runs on every exit past the Phase 1 preflight line — including exits before Phase 2 ever ran — but its worktree-removal block only fires when `$WT` is actually set; a Phase 1 early exit (`$WT` unset) skips removal, and `release --created "$CREATED_WT"` itself no-ops for a reused worktree. |
| Deleting `$PR_BRANCH` directly in Phase 7 cleanup | `release` is path-keyed and never issues a branch-deleting command — `$PR_BRANCH` is the real PR head branch and can never be destroyed by this step. |
| Post the reply before the commit | Always commit first (Phase 4) so `$FIX_SHA` is available for the ADDRESSED reply template. |
| Leave a CLARIFIED/DEFERRED **thread** open after reply | All three review-thread dispositions now resolve — an open thread blocks `/swe-workbench:review`'s approval gate. PR comments are unaffected (no thread to resolve). |
| Try to resolve via REST | Thread resolution is GraphQL-only (`resolveReviewThread` mutation). REST has no equivalent endpoint. |
| Re-present a thread the owner already clarified | On re-runs, skip *unresolved* threads that already have a comment authored by `$CURRENT_USER`. Detect via `comments.nodes[*].author.login`. |
