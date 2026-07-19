# Interrupted-hook recovery examples

Worked examples for both `HOOK_INTERRUPTED=1` cases from `## Failure Mode Table` in `SKILL.md`.

## Recovery Example — Interrupted Hook

A `SYNC_TIMEOUT` firing (or an external tool-call kill) can land mid-`rm` inside the rimba post-merge hook, leaving a worktree registered in `.git` with its directory already gone from disk. `sync-and-verify.sh` reports this as `HOOK_INTERRUPTED=1` and prints a recovery hint to stderr. The probe scans **all** registered worktrees, not just `$HEAD_REF`'s — `HOOK_INTERRUPTED=1` can point at an unrelated stray left over from a different branch's interrupted cleanup, so identify the specific entry before assuming it's the one you're cleaning up:

```bash
cd "$MAIN_REPO"
# Identify worktree(s) with no directory on disk (same check Block D performs; line-based, not awk field-splitting, so a path containing a space doesn't vanish):
git worktree list --porcelain | while IFS= read -r line; do
  case "$line" in
    "worktree "*) w=${line#worktree }; [ -d "$w" ] || echo "MISSING: $w" ;;
  esac
done
git worktree prune                              # drops the stale registration(s) for the missing dir(s)
git branch -D <stale-branch-name>                # the local ref that survived the interrupted rm
```

`git worktree prune` only removes registrations whose directories are gone — it never touches a live worktree, so it is safe to run unconditionally once `HOOK_INTERRUPTED=1` is observed. This does not need `--force`: prune has no dirty/unpushed concept because the directory it would check is already gone. If the missing entry turns out to be an unrelated stray (not `$HEAD_REF`), pruning it clears the signal and Step 4's normal removal strategies proceed for `$HEAD_REF` as usual.

## Recovery Example — Intact Root, Wiped Subtree

On a large worktree, a kill can land *after* the hook deletes most tracked files but *before* it removes the root directory. The missing-root scan above misses this (the directory is still there); the targeted subtree probe reports `HOOK_INTERRUPTED=1` with a message that deliberately does not suggest `git worktree prune` (a no-op here):

```bash
cd "$MAIN_REPO"
WT_PATH=$(git worktree list --porcelain \
  | awk -v ref="branch refs/heads/<headRefName>" '/^worktree /{p=$2} $0 == ref {print p; exit}')
git -C "$WT_PATH" restore .        # restores the missing tracked files from the index
# — or, to finish the interrupted removal instead —
rimba clean --merged --force
```

`restore .` only touches tracked files missing or modified relative to the index; untracked files are unaffected. After recovery, proceed with the normal flow from Step 4 onward for `$HEAD_REF`.
