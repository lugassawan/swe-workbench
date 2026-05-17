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
  gh pr view --json number,state,mergedAt,headRefName,headRepository
  ```
  Extract `headRefName` as the branch name to clean up.

### Step 2 — Verify Merged via `gh` (Sole Oracle)

```
gh pr view <number> --json state,mergedAt,headRefName
```

Read `state == "MERGED"` **and** `mergedAt != null`. Abort with a clear message if either condition fails.

**Never use `git branch --merged` as a merge check.** GitHub's default squash-merge strategy creates a new commit SHA on `main`; the original branch tip is not a merge ancestor of `main`, so `git branch --merged` silently lies. `gh` is the only oracle that does not lie.

### Step 3 — Free Session, Anchor cwd, Sync Local Main

**3a. Free the session from any active worktree.**

If the session is currently inside a worktree (e.g. entered via `EnterWorktree path=…`), call `ExitWorktree action=keep` now — *before* deriving `$MAIN_REPO` and *before* `git pull`. This:
- Returns the harness session to the directory it was in before the worktree was entered (not `$HOME`).
- Releases the harness's session lock on the worktree so the rimba post-merge hook (fired by `git pull` in 3c) can remove it cleanly.
- Ensures rimba's binary `remove` strategy (if reached) won't fire `git branch -D` from a deleted cwd.

If `EnterWorktree` was never called this session (or the `ExitWorktree` tool is unavailable), this step is a no-op — proceed to 3b without aborting.

**3b. Resolve the default branch, anchor cwd, sync, and verify hook cleanup.**

First, detect the default branch of the host repo:

```bash
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null \
  || git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' \
  || echo main)
```

Then invoke the companion script, passing the resolved default branch as `$2`:

```bash
_SCRIPTS="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/skills/workflow-cleanup-merged/scripts"
eval "$("$_SCRIPTS/sync-and-verify.sh" "<headRefName>" "$DEFAULT_BRANCH")"
```

The script: derives `MAIN_REPO=` (main worktree root via `git worktree list --porcelain`), anchors the shell there so the rimba hook cannot strand a deleted cwd, then syncs the default branch — **non-bare repos:** `git checkout "$DEFAULT_BRANCH" && git pull --ff-only origin "$DEFAULT_BRANCH"` (`--ff-only` is non-negotiable; plain `git pull` can synthesize a merge commit on divergence); **bare repos (rimba layout):** `git fetch origin "+refs/heads/$DEFAULT_BRANCH:refs/heads/$DEFAULT_BRANCH"` (bare repos have no working tree; `git fetch` advances the local ref directly). Both paths are best-effort — sync failure warns to stderr but does not abort.

When the rimba post-merge hook is active (see `### rimba + post-merge hook (fast path)`), `git pull` fires the hook as a side-effect, which removes the merged worktree and local branch automatically. **This applies to non-bare repos only** — in bare-repo layout `git fetch` is used instead, which does not fire `post-merge`; Block C will not get `WORKTREE_GONE=1` via the hook fast-path, but may still yield `WORKTREE_GONE=1` if the worktree and branch were already removed by other means. A sync failure on the fast path forces fall-through to the rimba-binary or shell strategy — it does NOT abort cleanup.

### Step 4 — Remove Worktree

`sync-and-verify.sh` (Step 3) emits `WORKTREE_GONE=0|1` into the shell environment via `eval`.

- **`WORKTREE_GONE=1`**: both the worktree and local branch are already gone — the hook did its job. No further action is needed in Step 4; skip Step 5 and proceed directly to Step 6.
- **`WORKTREE_GONE=0`**: hook did not fire (or rimba refused due to dirty/unpushed state). Select a removal strategy from `## Worktree Removal Strategies` below. Execute only the first strategy whose preconditions hold.

### Step 5 — Delete Local Branch (unconditional)

Always runs unless `WORKTREE_GONE=1` from Step 4:

```bash
git branch -D <headRefName>
```

Capital `-D` is required: squash-merged branches are not merge ancestors of `main`; lowercase `-d` would refuse.

### Step 6 — Delete Remote Branch

```
git push origin --delete <headRefName>
```

Treat HTTP 404 or "remote ref does not exist" as success — GitHub's `auto-delete-head-branches` repo setting commonly removes the remote branch on merge. Any other error: report it.

### Step 7 — Report

```
Cleanup complete for PR #<number> (<headRefName>):
  ✓ Worktree removed: <path>        (or: no worktree found — skipped)
  ✓ Local branch deleted: <branch>  (or: already gone)
  ✓ Remote branch deleted: <branch> (or: already gone)
  ✓ Local main synced to origin/main (or: ⚠ sync skipped — <reason>)
```

## Worktree Removal Strategies

Execute the first strategy whose preconditions hold. Fall through to the next if preconditions fail.

### rimba + post-merge hook (fast path)

**Preconditions — both must hold:**

1. `core.hooksPath` resolves to a directory containing an executable `post-merge` file that invokes `rimba clean --merged --force`. Detection:
   ```bash
   _SCRIPTS="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/skills/workflow-cleanup-merged/scripts"
   eval "$("$_SCRIPTS/check-rimba-hook.sh")"
   ```
   `RIMBA_HOOK_ACTIVE=1` is required. (The grep inside the script excludes comment-only lines so a documented-but-disabled invocation does not yield a false positive.)
2. After Step 3 sync, HEAD on `$MAIN_REPO` is on `$DEFAULT_BRANCH` (the hook's own branch guard requires it).

**Procedure:**

Nothing strategy-specific. The `git pull --ff-only origin "$DEFAULT_BRANCH"` in Step 3 fired the post-merge hook, which ran `rimba clean --merged --force` and removed the worktree and local branch as a side-effect.

The verification gate in Step 4 (`WORKTREE_GONE=1`) confirms the hook succeeded and routes the spine to skip Steps 4 and 5 directly to Step 6.

**Failure handling:**

The hook silently swallows errors (`|| true`). If the verification gate yields `WORKTREE_GONE=0` — because the hook didn't fire, rimba refused due to dirty/unpushed state, or sync failed — fall through to the `rimba (MCP / binary)` or `shell fallback` strategy below. No abort.

### rimba (MCP / binary)

**Preconditions:**
- rimba MCP server is active in the session, OR the rimba binary resolves on PATH or a known install location:
  ```bash
  _SCRIPTS="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/skills/workflow-cleanup-merged/scripts"
  RIMBA=$("$_SCRIPTS/resolve-rimba.sh")
  ```
  `RIMBA` must be non-empty (or MCP server active).

**Procedure:**
1. Run `$RIMBA remove <headRefName>` (or the `remove` tool on the `rimba mcp` server) — handles worktree location, dirty/unpushed checks, and removal internally.
2. For bulk stale-worktree cleanup (e.g., after a Mode C orchestration run), use `$RIMBA clean` instead.
3. (Once per repo) recommend the user run `rimba hook install` to automate future post-merge cleanups via a git hook — this removes the need for manual `/swe-workbench:cleanup-merged` invocations.

**Failure handling:**

If `$RIMBA remove` exits non-zero, run a filesystem probe as the canonical signal — do not rely on rimba's message text:
```bash
[ -d "<worktree-path>" ] && WORKTREE_STILL_PRESENT=1 || WORKTREE_STILL_PRESENT=0
```
- **`WORKTREE_STILL_PRESENT=0`** (worktree directory is gone): treat as **partial success** — the branch deletion failed but the worktree is already removed. `WORKTREE_GONE` remains `0` (Step 4 ran before rimba), so Step 5 executes normally. Fall through to Step 5 (`git branch -D`) from `$MAIN_REPO`. Do NOT abort.
- **`WORKTREE_STILL_PRESENT=1`** (worktree directory still exists — rimba refused, e.g. dirty/unpushed): report the rimba error verbatim and abort. Do not proceed to branch deletion.

### shell fallback

**Preconditions:**
- rimba is absent (previous strategy preconditions not met).

**Procedure:**

*Batch A — Locate Worktree + Safety Checks*

Run the companion script and eval its `KEY=VALUE` output:

```bash
_SCRIPTS="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/skills/workflow-cleanup-merged/scripts"
eval "$("$_SCRIPTS/probe-worktree.sh" "<headRefName>")"
```

- `WORKTREE`: matching worktree path, or empty if none (skip Batch B when empty).
- `DIRTY`: count of uncommitted-change lines. Must be 0; if not, abort — re-run `git -C "$WORKTREE" status --porcelain` to show files.
- `UNPUSHED`: count of unpushed commits. Must be 0; if not, abort — re-run `git -C "$WORKTREE" log @{upstream}..HEAD` to list them.

*[Optional] cwd-fix*

If `cwd` is a subdirectory of `$WORKTREE`, cd to the main repo root before removal:
```
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
- `WORKTREE` empty: skip Batch B. Proceed directly to Step 5 (local branch delete).

## Failure Mode Table

| Failure | Signal | Action |
|---------|--------|--------|
| PR not yet merged | `state != "MERGED"` or `mergedAt == null` | Abort. Print PR state and URL. Do not delete anything. |
| Uncommitted changes in worktree | `DIRTY > 0` | Abort. Re-run `git status --porcelain` to show files. Tell user to stash or commit first. |
| Unpushed commits in worktree | `UNPUSHED > 0` | Abort. Re-run `git log @{upstream}..HEAD` to list commits. Tell user to push or discard first. |
| cwd is inside the worktree | Path comparison | `cd` to main repo root before Batch B, or abort if not possible. |
| `git worktree remove` fails | Non-zero exit | Abort. Do not delete branches. Report verbatim. |
| No matching worktree found | `WORKTREE` empty | Skip Batch B. Proceed directly to Step 5 (local branch delete). |
| Remote branch already gone | HTTP 404 / "remote ref does not exist" | Treat as success. Report "already gone". |
| Step 3 (sync main) fails | Non-zero exit from `git checkout` or `git pull` | Warn in report. Do not abort — sync is best-effort; cleanup proceeds. |
| PR number not derivable from current branch | `gh pr view` fails | Ask the user for the PR number explicitly. |
| Hook ran but did not clean | `WORKTREE_GONE=0` after sync despite hook active | Fall through to rimba-binary or shell strategy. No abort. |
| cwd deleted mid-flow by hook | `fatal: not a git repository` on next command | Step 3a `ExitWorktree action=keep` prevents this when followed. If observed, re-run from the main repo root. |
| rimba `remove` removes worktree but fails branch delete | Non-zero exit after worktree directory is gone | Partial success — fall through to Step 5 from `$MAIN_REPO`. Worktree is gone; only branch remains. |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Use `git branch --merged` to check if a PR is merged | Never. Squash-merges lie. Use `gh pr view --json state,mergedAt`. |
| Use lowercase `git branch -d` | Always use `-D`. Squash-merged branches are not merge ancestors of `main`. |
| Force-delete a worktree with dirty state | Never. Batch A aborts before Batch B runs. |
| Run cleanup from inside the worktree being deleted | Step 3 anchors cwd to $MAIN_REPO before the pull. If skipped, the rimba hook can delete the cwd mid-flight and strand subsequent commands with "fatal: not a git repository". |
| Skip `ExitWorktree action=keep` in a session entered via `EnterWorktree` | Always call it as the first action of Step 3 when the tool is available. Without it, the harness session lock remains on the worktree when `git pull` fires the rimba hook — rimba's child process inherits a cwd that gets deleted mid-operation, leaving the branch undeleted and the session stranded at `$HOME`. |
| Auto-trigger cleanup on merge | Never. Cleanup is user-initiated or explicitly orchestrated. No Stop hooks. |
| Treat remote-404 as an error | It is success — `auto-delete-head-branches` already removed it. |
| Use plain `git pull origin main` for the sync | Always `--ff-only`. Plain pull can synthesize a merge commit. |
| Check `.githooks/post-merge` directly for hook presence | Always resolve via `git config --get core.hooksPath` — the file exists in the repo but is only active when `core.hooksPath` points to its parent. |
