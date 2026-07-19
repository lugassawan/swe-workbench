---
name: workflow-cleanup-merged
description: Use after a PR has been merged on GitHub to remove the local worktree, delete the local branch, delete the remote branch, and fast-forward local main — safely, with squash-merge support.
orchestrator: true
---

# Workflow: Cleanup Merged Branch

**Announce at start:** "I'm using the workflow-cleanup-merged skill to clean up after the merged PR."

## When to Invoke

- After the user has confirmed a PR is merged on GitHub.
- Invoked by `/swe-workbench:cleanup-merged` (user-triggered, one-off cleanup).
- Invoked by Mode C orchestration (`orchestration.md`) at Step 7, after each merge round.

**Never auto-trigger.** Cleanup is user-initiated or orchestrator-initiated. Do not attach to a Stop hook.

## What This Skill Does NOT Do

- Does not merge PRs — that is the user's action.
- Does not force-delete branches with uncommitted work — no `--force`, ever.
- Does not squash, rebase, or alter commit history.
- Does not bypass branch protection rules.
- Does not verify CI status — CI verification happens in Phase 3/4 before the PR is created.

## Cleanup Contract

### Step 1 — Resolve Target PR

- If the user passed a PR number → use it directly.
- Else → derive from current branch:
  ```
  gh pr view --json number,state,mergedAt,headRefName,headRepository,body
  ```
  Extract `headRefName` as the branch name to clean up.

### Step 2 — Verify Merged via `gh` (Sole Oracle)

```
gh pr view <number> --json state,mergedAt,headRefName,body
```

Read `state == "MERGED"` **and** `mergedAt != null`. Abort with a clear message if either condition fails.

**Never use `git branch --merged` as a merge check.** GitHub's default squash-merge strategy creates a new commit SHA on `main`; the original branch tip is not a merge ancestor of `main`, so `git branch --merged` silently lies. `gh` is the only oracle that does not lie.

### Step 3 — Free Session, Anchor cwd, Sync Local Main

**3a. Free the session from any active worktree.**

If the session is currently inside a worktree (e.g. entered via `EnterWorktree path=…`), call `ExitWorktree action=keep` now — *before* deriving `$MAIN_REPO` and *before* `git pull`. This:
- Returns the harness session to the directory it was in before the worktree was entered (not `$HOME`).
- Releases the harness's session lock on the worktree so the rimba post-merge hook (fired by `git pull` in 3c) can remove it cleanly.
- Ensures rimba's binary `remove` strategy (if reached) won't fire `git branch -D` from a deleted cwd.

If `ExitWorktree` reports a no-op, that means only *no active `EnterWorktree` session* — caused by either `cd`-fallback entry **or** compaction dropping harness-level `EnterWorktree` tracking (indistinguishable from the tool's output alone; see `workflow-worktree-session` Mode C for the full ambiguity-aware diagnostic). Either way, recover the same way: `cd` to the main repo root before deriving `$MAIN_REPO` and running `git pull`:

```bash
_GCD=$(git rev-parse --git-common-dir)
# relative (.git) means we're already at main root — nothing to do
[[ "$_GCD" != /* ]] || cd "${_GCD%/.git}"
```

`git rev-parse --git-common-dir` returns the path to the common `.git` directory — absolute from a linked worktree (e.g. `/path/to/main/.git`), relative (`.git`) from the main worktree itself. The guard `[[ "$_GCD" != /* ]]` skips the `cd` when already at main root (this includes the case where `EnterWorktree` was never called and the cwd is not inside any worktree — the relative `.git` result causes the guard to short-circuit, making the command a no-op). **Assumes a standard embedded `.git` directory**; repos created with `--separate-git-dir` or submodule common dirs (e.g. `.git/modules/sub`) may return a path that does not end in `/.git`, in which case `${_GCD%/.git}` is a no-op and a different navigation strategy is needed.

**3b. Resolve the default branch, anchor cwd, sync, and verify hook cleanup.**

First, detect the default branch of the host repo:

```bash
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null \
  || git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' \
  || echo main)
```

Then invoke the companion script, passing the resolved default branch as `$2`:

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
[ -f "$_RT/runtime/clean-state-files.sh" ] || {
  echo "swe-workbench runtime scripts not found under $_RT/runtime — set CLAUDE_PLUGIN_ROOT and retry." >&2
  exit 1
}
_SCRIPTS="$_RT/skills/workflow-cleanup-merged/scripts"
eval "$("$_SCRIPTS/sync-and-verify.sh" "<headRefName>" "$DEFAULT_BRANCH")"
```

**⚠️ Bash-tool timeout coupling (must hold, not optional):** invoke this Bash tool call with an explicit `timeout: 600000` (~600s). The script's own internal watchdog computes an adaptive budget capped at ~570s (see `TOTAL_CAP` in `sync-and-verify.sh`) precisely so it fires *before* the harness's external tool-call timeout. Bash's own default tool-call timeout is 120s — well under the script's worst-case adaptive budget on a large monorepo worktree. If the external timeout fires first, the harness kills the whole process tree uncontrolled: the internal watchdog never gets to run its own controlled TERM→KILL sequence, and Block D's detection code never executes — the interrupted-hook state goes undetected and unreported. The script cannot self-enforce this invariant; it depends entirely on the caller passing this explicit timeout.

The script: derives `MAIN_REPO=` (main worktree root via `git worktree list --porcelain`), anchors the shell there so the rimba hook cannot strand a deleted cwd, then runs `git checkout "$DEFAULT_BRANCH" && git pull --ff-only origin "$DEFAULT_BRANCH"` (best-effort — sync failure warns to stderr but does not abort), then checks whether the hook already removed the worktree and local branch. `--ff-only` is non-negotiable; plain `git pull` can synthesize a merge commit on divergence.

When the rimba post-merge hook is active (see `### rimba + post-merge hook (fast path)`), `git pull` fires the hook as a side-effect, which removes the merged worktree and local branch automatically. A sync failure on the fast path forces fall-through to the rimba-binary or shell strategy — it does NOT abort cleanup.

**Internal timeout guard — split, adaptive budget.** The checkout-then-pull sync step runs under a `SYNC_TIMEOUT` watchdog — a pure-bash `set -m` job-group backgrounding, not the `timeout` binary (absent on stock macOS). By default (no `SYNC_TIMEOUT` override) the budget is computed adaptively as `PULL_BUDGET` (network allowance, `90`s, override via `PULL_TIMEOUT`) **plus** `HOOK_BUDGET` — scaled by `$HEAD_REF`'s own tracked-file count (`git ls-files | wc -l` on its worktree, capped at `480`s) — so a hook cleaning up a worktree with tens of thousands of tracked files gets a proportionally larger window instead of being starved by a flat 90s. The total is capped at `570`s (`TOTAL_CAP`). An explicit `SYNC_TIMEOUT` env var always overrides this computation verbatim (with the existing non-negative-integer validation, falling back to 90 on invalid input) — this is how the test suite pins specific watchdog timings. The script emits a stderr diagnostic (`adaptive watchdog budget=<T>s (pull=<P>s + hook=<H>s for <files> tracked files)`) whenever the adaptive path runs. If the pull+hook combined exceeds the budget, the watchdog `kill`s the whole process group. **What the guard does and does not do:** it does NOT prevent corruption — an external kill (or the internal watchdog itself) can still land mid-`rm` inside the rimba post-merge hook, leaving a worktree with an intact root but wiped tracked files. It converts an otherwise-uncontrolled kill (which would also take down this script mid-hook, leaving the failure silent) into a controlled in-script timeout that still runs Block D's detection below.

**Hook-interruption detection (stateless, not event-based).** After the sync, the script runs checks that set `HOOK_INTERRUPTED=1`:

1. **Missing-root scan** — probes `git worktree list --porcelain` for any registered worktree whose *top-level directory* is missing on disk — the signal that a `post-merge` hook `rm` (this run's or a prior one's) was interrupted mid-deletion before reaching the worktree's own root removal, leaving the worktree registration and branch ref alive in `.git` while the whole directory is gone.
2. **Targeted subtree-wipe probe** — checks `$HEAD_REF`'s own worktree specifically: if its root directory still exists but ≥90% of its tracked files (by `git status --porcelain` deletion count vs. the `git ls-files` total) are gone, the hook was interrupted *after* deleting most files but *before* removing the root itself. The missing-root scan above cannot see this case — the directory is still there. A ratio threshold (not "any deletion") avoids flagging a worktree that's just legitimately dirty.
3. **Probe-failure fallback** — if the subtree-wipe probe's own `git status` call fails (e.g. `$HEAD_WT`'s admin metadata was itself reaped before a kill landed), the script does not default to "0% deleted" — it flags `HOOK_INTERRUPTED=1` with a distinct "could not verify" stderr message, since a failed probe is inconclusive, not evidence of a clean worktree. All three checks are state-based rather than event-based on purpose: an external kill takes down this script too, so it cannot reliably observe its own interruption — but a stale registration, a wiped subtree, or an unverifiable state on the next run always tells the truth.

### Step 4 — Remove Worktree

`sync-and-verify.sh` (Step 3) emits two `KEY=VALUE` lines into the shell environment via `eval`: `WORKTREE_GONE=0|1` and `HOOK_INTERRUPTED=0|1`.

- **`WORKTREE_GONE=1`**: both the worktree and local branch are already gone — the hook did its job. No further action is needed in Step 4; proceed to Step 5. The script reports `LOCAL_DELETED=0` (local already gone) and still attempts the remote delete.
- **`WORKTREE_GONE=0`**: hook did not fire (or rimba refused due to dirty/unpushed state). Select a removal strategy from `## Worktree Removal Strategies` below. Execute only the first strategy whose preconditions hold.
- **`HOOK_INTERRUPTED=1`**: independent of `WORKTREE_GONE` — one of three states, all meaning the timeout guard (or an external kill on a prior run) caught the post-merge hook mid-`rm`. The script is verify-only here: it signals and documents, it never auto-remediates.
  - **Root missing** — a registered worktree exists in `.git` with no directory on disk at all. The probe scans **all** registered worktrees, not just `$HEAD_REF`'s — the flagged entry may be `$HEAD_REF`'s own half-deleted worktree, or an unrelated stray left over from a different branch's interrupted cleanup. Either way, run `git worktree prune` first (always safe — see the Recovery Example below); if the missing entry was `$HEAD_REF`'s own, its worktree is now fully gone and only its branch remains (skip straight to Step 5). If it was an unrelated stray, pruning clears the signal and the normal Step 4 removal strategies proceed for `$HEAD_REF` as usual.
  - **Root intact, subtree wiped** — `$HEAD_REF`'s own worktree directory still exists, but ≥90% of its tracked files are gone from disk (the hook was killed after deleting most files but before removing the root). `git worktree prune` is a **no-op** here — it only clears missing *directories*, and this one still exists. Recover with `git -C <worktree-path> restore .` (restores the missing tracked files from the index) or by re-running `rimba clean --merged --force` to finish the interrupted removal, then proceed with the normal flow from Step 4 onward.
  - **Root intact, probe inconclusive** — the subtree-wipe probe's own `git status` call failed (e.g. `$HEAD_WT`'s admin metadata was itself reaped). Neither `git worktree prune` (directory exists) nor `restore .` (needs functioning git metadata) is guaranteed safe here — manually inspect `$HEAD_WT` (e.g. `git -C <worktree-path> status`) before choosing a recovery path.

### Step 5 — Residual Sweep (PR-scoped)
```bash
_SCRIPTS="$_RT/skills/workflow-cleanup-merged/scripts"
eval "$("$_SCRIPTS/sweep-residuals.sh" "<number>")"
```
This is a **backstop**, not a replacement for each flow's own Phase 7 cleanup: it force-removes any leftover `#<number>`-keyed ephemeral artifacts from `workflow-pr-review`, `workflow-pr-review-followup`, and `workflow-address-feedback` when their own cleanup failed or was interrupted — the reviewer worktrees `pr-review-<number>` and `pr-followup-<number>` (plus their bare-`<number>` `/tmp` fallback paths) and both reviewer branches, the `address-feedback-<number>` worktree, and `#<number>`'s orphaned `/tmp` state JSON (Step 2 already proved `#<number>` is `MERGED`, so this force-removal is safe). It never deletes the `address-feedback-<number>` branch — that may be the PR's real head branch — and never touches the shared containing dirs `/tmp/swe-workbench-pr-review/` or `/tmp/swe-workbench-address-feedback/`, since a concurrent unrelated PR may hold live state there. Worktrees with uncommitted changes are skipped rather than force-removed, with a stderr warning, so an interrupted session's local-only work is never silently discarded. **This runs before Step 6's branch deletion on purpose:** a stale `address-feedback-<number>` worktree checks out the PR's real head branch directly, so if it still exists, Step 6's `git branch -D` would be refused by git and silently swallowed by `eval` unless this sweep clears it first. The script emits `SWEPT_WORKTREES=<n>`, `SWEPT_STATE_FILES=<n>`, `RESIDUAL_NONE=0|1` via `eval` and always exits 0. After it runs, also delete any scratchpad files **you** (the agent executing this skill) created for this PR's review/feedback/cleanup work — scoped to `#<number>` only, never a blanket wipe of the scratchpad directory; the harness scratchpad path layout is undocumented and version-fragile, so this step stays prose guidance rather than shipped shell code.

### Step 6 — Delete Branches
```bash
eval "$("$_SCRIPTS/delete-branches.sh" "<headRefName>")"
```
The script self-detects `MAIN_REPO` and anchors `cd` internally. It emits exactly two `KEY=VALUE` lines:
- `LOCAL_DELETED=0|1` — `1` if the script deleted the local branch; `0` if it was already gone.
- `REMOTE_DELETED=0|1` — `1` if the script deleted the remote branch; `0` if it was already gone.

The script always attempts the remote delete regardless of whether the local branch was present — this covers the `WORKTREE_GONE=1` path where the local branch was already removed by the rimba hook. HTTP 404 / "remote ref does not exist" is treated as success (`REMOTE_DELETED=0`). Any other push error is warned to stderr but the script exits 0 so the caller's `eval` never aborts mid-cleanup. Capital `-D` is used for the local delete: squash-merged branches are not merge ancestors of `main`; lowercase `-d` would refuse.

### Step 7 — Report

Print this 4-line block immediately — cleanup Steps 3–6 are already done at this point, and this
confirmation must not wait on Step 8, which runs (and may pause on `AskUserQuestion`) afterward.

```
Cleanup complete for PR #<number> (<headRefName>):
  ✓ Worktree removed: <path>        (or: no worktree found — skipped)
  ✓ Residual sweep: <SWEPT_WORKTREES> worktree(s) + <SWEPT_STATE_FILES> state file(s) removed (or: none)
  ✓ Branches deleted: local <branch> / remote <branch> (or: already gone — LOCAL_DELETED=0 / REMOTE_DELETED=0)
  ✓ Local main synced to origin/main (or: ⚠ sync skipped — <reason>)
```

### Step 8 — Deferred-verification follow-up

Only when the `body` fetched in Step 1/2 contains the exact line
`<!-- swe-workbench:deferred-verification -->` (written by `/swe-workbench:hotfix` when the fix
shipped ahead of its regression test). Steps 3–6 always complete unconditionally first — this step
never gates cleanup, and marker-absent PRs skip it silently with the Step 7 report unchanged.

Offer `AskUserQuestion`: **File a follow-up issue** / **Create a `test/<slug>` branch** (off the
already-synced default branch from Step 3) / **Skip**. Full filing mechanics (preview + `.cmd`
sidecar + `confirm` gate, mirroring `workflow-audit-emit-issues`, scoped to "Backfill regression
test for hotfix PR #<number>", `--label` included when a matching repo label exists) are in
`reference/deferred-verification-followup.md`.

Once Step 8 resolves (filed, branched, or skipped), append one trailing line to the already-printed
Step 7 report — do not reprint the 4-line block:

```
  ✓ Follow-up: <filed as issue #N | test/<slug> branch created | skipped>
```

## Worktree Removal Strategies
Execute the first strategy whose preconditions hold. Fall through to the next if preconditions fail.

### rimba + post-merge hook (fast path)

**Preconditions — both must hold:**

1. `core.hooksPath` resolves to a directory containing an executable `post-merge` file that invokes `rimba clean --merged --force`. Detection:
   ```bash
   _SCRIPTS="$_RT/skills/workflow-cleanup-merged/scripts"
   eval "$("$_SCRIPTS/check-rimba-hook.sh")"
   ```
   `RIMBA_HOOK_ACTIVE=1` is required. (The grep inside the script excludes comment-only lines so a documented-but-disabled invocation does not yield a false positive.)
2. After Step 3 sync, HEAD on `$MAIN_REPO` is on `$DEFAULT_BRANCH` (the hook's own branch guard requires it).

**Procedure:**

Nothing strategy-specific. The `git pull --ff-only origin "$DEFAULT_BRANCH"` in Step 3 fired the post-merge hook, which ran `rimba clean --merged --force` and removed the worktree and local branch as a side-effect.

The verification gate in Step 4 (`WORKTREE_GONE=1`) confirms the hook succeeded and routes the spine to skip Step 4 worktree-removal strategies and proceed through Step 5 (residual sweep) to Step 6 (reports `LOCAL_DELETED=0`, still deletes remote).

**Failure handling:**

The hook silently swallows errors (`|| true`). If the verification gate yields `WORKTREE_GONE=0` — because the hook didn't fire, rimba refused due to dirty/unpushed state, or sync failed — fall through to the `rimba (MCP / binary)` or `shell fallback` strategy below. No abort.

### rimba (MCP / binary)

**Preconditions:**
- rimba MCP server is active in the session, OR the rimba binary resolves on PATH or a known install location:
  ```bash
  _SCRIPTS="$_RT/skills/workflow-cleanup-merged/scripts"
  RIMBA=$("$_SCRIPTS/resolve-rimba.sh")
  ```
  `RIMBA` must be non-empty (or MCP server active).

**Procedure:**

1. **Route by how rimba is available** (mirror the MCP → binary → shell ordering of `skills/workflow-development/SKILL.md:113-116`):
   - **rimba MCP server active in session** → invoke the rimba `remove` tool (`task: <headRefName>`); for bulk stale-worktree cleanup (e.g., after a Mode C orchestration run) invoke the `clean` tool (`mode: merged` — equivalent to the binary's `--merged` flag). No shell process needed.
   - **`$RIMBA` non-empty (binary resolved by `resolve-rimba.sh`)** → run `$RIMBA remove <headRefName>` (or `$RIMBA clean --merged` for bulk cleanup — same scope as the hook at line 136; `--force` is intentionally omitted for manual use).
   - **rimba absent** → fall through to the **shell fallback** strategy below.

   Either rimba path handles worktree location, dirty/unpushed checks, and removal internally.
2. (Once per repo) recommend the user run `rimba hook install` to automate future post-merge cleanups via a git hook — this removes the need for manual `/swe-workbench:cleanup-merged` invocations.

**Failure handling:**

If the rimba `remove` or `clean` (MCP tool or `$RIMBA` binary) reports failure, run a filesystem probe as the canonical signal — do not rely on rimba's message text:
```bash
[ -d "<worktree-path>" ] && WORKTREE_STILL_PRESENT=1 || WORKTREE_STILL_PRESENT=0
```
- **`WORKTREE_STILL_PRESENT=0`** (worktree directory is gone): treat as **partial success** — the branch deletion failed but the worktree is already removed. `WORKTREE_GONE` remains `0` (Step 4 ran before rimba), so Step 5 and Step 6 execute normally. Fall through to Step 6 (`delete-branches.sh`) from `$MAIN_REPO`. Do NOT abort.
- **`WORKTREE_STILL_PRESENT=1`** (worktree directory still exists — rimba refused, e.g. dirty/unpushed): report the rimba error verbatim and abort. Do not proceed to branch deletion.

### shell fallback

**Preconditions:**
- rimba is absent (previous strategy preconditions not met).

**Procedure:**

*Batch A — Locate Worktree + Safety Checks*

Run the companion script and eval its `KEY=VALUE` output:

```bash
_SCRIPTS="$_RT/skills/workflow-cleanup-merged/scripts"
eval "$("$_SCRIPTS/probe-worktree.sh" "<headRefName>")"
```

- `WORKTREE`: matching worktree path, or empty if none (skip Batch B when empty).
- `DIRTY`: count of uncommitted-change lines. Must be 0; if not, abort — re-run `git -C "$WORKTREE" status --porcelain` to show files.
- `UNPUSHED`: count of unpushed commits. Must be 0; if not, abort — re-run `git -C "$WORKTREE" log @{upstream}..HEAD` to list them.

*[Optional] cwd-fix*

If `cwd` is a subdirectory of `$WORKTREE`, cd to the worktree root before removal:
```bash
cd "$(git rev-parse --show-toplevel)"
```

*Batch B — Remove Worktree*

Only run if `WORKTREE` is non-empty. If `git worktree remove` fails, abort and report the error verbatim — do not proceed to local branch deletion.

```bash
git worktree remove "$WORKTREE"
```

**Failure handling:**
- `DIRTY > 0`: abort. Re-run `git status --porcelain` to show files. Tell user to stash or commit first.
- `UNPUSHED > 0`: abort. Re-run `git log @{upstream}..HEAD` to list commits. Tell user to push or discard first.
- `git worktree remove` fails: abort. Do not delete branches. Report verbatim.
- `WORKTREE` empty: skip Batch B. Proceed directly to Step 6 (delete branches).

## Failure Mode Table

| Failure | Signal | Action |
|---------|--------|--------|
| PR not yet merged | `state != "MERGED"` or `mergedAt == null` | Abort. Print PR state and URL. Do not delete anything. |
| Uncommitted changes in worktree | `DIRTY > 0` | Abort. Re-run `git status --porcelain` to show files. Tell user to stash or commit first. |
| Unpushed commits in worktree | `UNPUSHED > 0` | Abort. Re-run `git log @{upstream}..HEAD` to list commits. Tell user to push or discard first. |
| cwd is inside the worktree | Path comparison | `cd` to the worktree root (`git rev-parse --show-toplevel`) before Batch B, or abort if not possible. |
| `git worktree remove` fails | Non-zero exit | Abort. Do not delete branches. Report verbatim. |
| No matching worktree found | `WORKTREE` empty | Skip Batch B. Proceed directly to Step 6 (delete branches). |
| Remote branch already gone | HTTP 404 / "remote ref does not exist" | Treat as success. Report "already gone". |
| Step 3 (sync main) fails | Non-zero exit from `git checkout` or `git pull` | Warn in report. Do not abort — sync is best-effort; cleanup proceeds. |
| PR number not derivable from current branch | `gh pr view` fails | Ask the user for the PR number explicitly. |
| Hook ran but did not clean | `WORKTREE_GONE=0` after sync despite hook active | Fall through to rimba-binary or shell strategy. No abort. |
| cwd deleted mid-flow by hook | `fatal: not a git repository` on next command | Step 3a `ExitWorktree action=keep` (or the `cd`-to-main-root fallback for `cd`-entered worktrees) prevents this when followed. If observed, re-run from the main repo root. |
| rimba `remove` removes worktree but fails branch delete | Non-zero exit after worktree directory is gone | Partial success — fall through to Step 6 from `$MAIN_REPO`. Worktree is gone; only branch remains. |
| Partial worktree deletion (interrupted hook, root missing) | `HOOK_INTERRUPTED=1` — a registered worktree is missing on disk (may be `$HEAD_REF`'s own, or an unrelated stray from an earlier interrupted cleanup) | Run `git worktree prune` from `$MAIN_REPO` first — always safe, never touches a live worktree — then delete the stale branch (`delete-branches.sh` or `git branch -D <ref>`). Only skip the normal Step 4 removal strategies for `$HEAD_REF` if the missing entry turns out to be `$HEAD_REF`'s own worktree; otherwise proceed with Step 4 as usual once the stray is pruned. |
| Partial worktree deletion (interrupted hook, root intact / subtree wiped) | `HOOK_INTERRUPTED=1` — `$HEAD_REF`'s own worktree directory still exists but ≥90% of its tracked files are gone | `git worktree prune` is a no-op (the directory exists). Run `git -C <worktree-path> restore .` to restore the missing files, or re-run `rimba clean --merged --force` to finish the interrupted removal, then proceed with the normal flow from Step 4 onward. |
| Subtree-wipe probe itself fails (interrupted hook, root intact, state unverifiable) | `HOOK_INTERRUPTED=1` — stderr shows "could not verify \<worktree\>'s worktree state" | Neither `git worktree prune` nor `restore .` is guaranteed safe. Manually inspect `$HEAD_WT` (e.g. `git -C <worktree-path> status`) before choosing a recovery path. |

### Recovery Examples

Worked examples for both `HOOK_INTERRUPTED=1` cases (root-missing, and the root-intact/subtree-wiped
case) — including the exact `git worktree prune` / `git -C <path> restore .` / `rimba clean
--merged --force` recovery commands named above — live in `reference/recovery-examples.md`.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Use `git branch --merged` to check if a PR is merged | Never. Squash-merges lie. Use `gh pr view --json state,mergedAt`. |
| Use lowercase `git branch -d` | Always use `-D`. Squash-merged branches are not merge ancestors of `main`. |
| Force-delete a worktree with dirty state | Never. Batch A aborts before Batch B runs. |
| Run cleanup from inside the worktree being deleted | Step 3 anchors cwd to $MAIN_REPO before the pull. If skipped, the rimba hook can delete the cwd mid-flight and strand subsequent commands with "fatal: not a git repository". |
| Skip `ExitWorktree action=keep` in a session entered via `EnterWorktree` | Always call it as the first action of Step 3 when the tool is available. Without it, the harness session lock remains on the worktree when `git pull` fires the rimba hook — rimba's child process inherits a cwd that gets deleted mid-operation, leaving the branch undeleted and the session stranded at `$HOME`. If `ExitWorktree` reports a no-op — cd-fallback entry **or** compaction dropped tracking, not confirmed cd-entry — use the `cd`-to-main-root command in Step 3a instead. |
| Auto-trigger cleanup on merge | Never. Cleanup is user-initiated or explicitly orchestrated. No Stop hooks. |
| Treat remote-404 as an error | It is success — `auto-delete-head-branches` already removed it. |
| Use plain `git pull origin main` for the sync | Always `--ff-only`. Plain pull can synthesize a merge commit. |
| Check `.githooks/post-merge` directly for hook presence | Always resolve via `git config --get core.hooksPath` — the file exists in the repo but is only active when `core.hooksPath` points to its parent. |
