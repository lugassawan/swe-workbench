# Worktree removal strategies

Full detail for `SKILL.md` Step 4's `## Worktree Removal Strategies` — the three mutually exclusive removal paths. Execute the first strategy whose preconditions hold. Fall through to the next if preconditions fail.

## rimba + post-merge hook (fast path)

**Preconditions — both must hold:**

1. `core.hooksPath` resolves to a directory containing an executable `post-merge` file that invokes `rimba clean --merged --force`. Detection:
   ```bash
   eval "$(swe-workbench-skill-script workflow-cleanup-merged check-rimba-hook.sh)"
   ```
   `RIMBA_HOOK_ACTIVE=1` is required. (The grep inside the script excludes comment-only lines so a documented-but-disabled invocation does not yield a false positive.)
2. After Step 3 sync, HEAD on `$MAIN_REPO` is on `$DEFAULT_BRANCH` (the hook's own branch guard requires it).

**Procedure:**

Nothing strategy-specific. The `git pull --ff-only origin "$DEFAULT_BRANCH"` in Step 3 fired the post-merge hook, which ran `rimba clean --merged --force` and removed the worktree and local branch as a side-effect.

The verification gate in Step 4 (`WORKTREE_GONE=1`) confirms the hook succeeded and routes the spine to skip Step 4 worktree-removal strategies and proceed through Step 5 (residual sweep) to Step 6 (reports `LOCAL_DELETED=0`, still deletes remote).

**Failure handling:**

The hook silently swallows errors (`|| true`). If the verification gate yields `WORKTREE_GONE=0` — because the hook didn't fire, rimba refused due to dirty/unpushed state, or sync failed — fall through to the `rimba (MCP / binary)` or `shell fallback` strategy below. No abort.

## rimba (MCP / binary)

**Preconditions:**
- rimba MCP server is active in the session, OR the rimba binary resolves on PATH or a known install location:
  ```bash
  RIMBA=$(swe-workbench-skill-script workflow-cleanup-merged resolve-rimba.sh)
  ```
  `RIMBA` must be non-empty (or MCP server active).

**Procedure:**

1. **Route by how rimba is available** (mirror the MCP → binary → shell ordering used for rimba resolution in `skills/workflow-development/reference/branch-resolution.md`):
   - **rimba MCP server active in session** → invoke the rimba `remove` tool (`task: <headRefName>`); for bulk stale-worktree cleanup (e.g., after a Mode C orchestration run) invoke the `clean` tool (`mode: merged` — equivalent to the binary's `--merged` flag). No shell process needed.
   - **`$RIMBA` non-empty (binary resolved by `resolve-rimba.sh`)** → run `$RIMBA remove <headRefName>` (or `$RIMBA clean --merged` for bulk cleanup — same scope as the "rimba + post-merge hook (fast path)" section's `rimba clean --merged --force` above, `--force` intentionally omitted here for manual use).
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

## shell fallback

**Preconditions:**
- rimba is absent (previous strategy preconditions not met).

**Procedure:**

*Batch A — Locate Worktree + Safety Checks*

Run the companion script and eval its `KEY=VALUE` output:

```bash
eval "$(swe-workbench-skill-script workflow-cleanup-merged probe-worktree.sh "<headRefName>")"
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
