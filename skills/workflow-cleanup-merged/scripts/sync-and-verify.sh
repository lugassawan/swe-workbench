#!/usr/bin/env bash
# Anchors cwd to the main repo, syncs local main, and checks whether the
# rimba post-merge hook already cleaned up the given branch.
# Usage: sync-and-verify.sh <head_ref> [default_branch]
# Stdout contract: WORKTREE_GONE=0|1 <newline> HOOK_INTERRUPTED=0|1
# Exit non-zero only if $MAIN_REPO cannot be resolved.
set -euo pipefail

HEAD_REF="${1:?Usage: sync-and-verify.sh <head_ref> [default_branch]}"
DEFAULT_BRANCH="${2:-$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo main)}"

# Block A: derive $MAIN_REPO and anchor cwd
MAIN_REPO=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
[ -n "${MAIN_REPO:-}" ] || { echo "sync-and-verify: could not resolve main repo path — aborting" >&2; exit 1; }
cd "$MAIN_REPO"

# Block B: sync local default branch (best-effort — failure warns, does not abort)
# Backgrounded under an internal watchdog so an external tool-call kill can
# never hit this step uncontrolled: firing before that external timeout turns
# an unrecoverable process-tree kill into a controlled in-script exit that
# still runs Block D's detection. This does NOT prevent corruption — a kill
# can still land during the hook's rm — it makes it detectable and recoverable.
# SYNC_TIMEOUT must be < the external tool-call timeout (headroom for Block C/D
# plus the 2s kill grace below) — the script cannot self-enforce this invariant.
SYNC_TIMEOUT="${SYNC_TIMEOUT:-90}"
case "$SYNC_TIMEOUT" in
  ''|*[!0-9]*)
    echo "sync-and-verify: invalid SYNC_TIMEOUT='$SYNC_TIMEOUT' (must be a non-negative integer) — falling back to 90" >&2
    SYNC_TIMEOUT=90
    ;;
esac
TIMED_OUT=0
set -m # give the backgrounded job its own process group
( git checkout "$DEFAULT_BRANCH" \
    && git pull --ff-only origin "$DEFAULT_BRANCH" ) >/dev/null 2>&1 &
job=$!
elapsed=0
while kill -0 "$job" 2>/dev/null; do
  if [ "$elapsed" -ge "$SYNC_TIMEOUT" ]; then
    kill -TERM -"$job" 2>/dev/null || true # negative PID = whole group: git + orphaned rimba hook child
    sleep 2
    kill -KILL -"$job" 2>/dev/null || true
    TIMED_OUT=1
    break
  fi
  sleep 1
  elapsed=$((elapsed + 1)) # NOT ((elapsed++)) — returns 1 (falsy) at 0, trips set -e
done
pull_rc=0
wait "$job" 2>/dev/null || pull_rc=$? # `wait; pull_rc=$?` on separate lines is unreachable under set -e
set +m

if [ "$TIMED_OUT" -eq 0 ] && [ "$pull_rc" -ne 0 ]; then
  echo "sync-main: best-effort failed — reconcile $DEFAULT_BRANCH manually (run git pull to see the underlying error)" >&2
fi

# Block C: verification gate — check whether hook already cleaned up
# Use awk string comparison (-v) to avoid regex metachar injection from HEAD_REF
WORKTREE_FOUND=$(git worktree list --porcelain \
  | awk -v ref="branch refs/heads/$HEAD_REF" '$0 == ref {print 1; exit}')
if git rev-parse --verify "refs/heads/$HEAD_REF" >/dev/null 2>&1; then
  BRANCH_FOUND=1
else
  BRANCH_FOUND=
fi

WORKTREE_GONE=0
[ -z "${WORKTREE_FOUND:-}" ] && [ -z "${BRANCH_FOUND:-}" ] && WORKTREE_GONE=1

# Block D: partial-deletion probe — canonical state-based signal that the
# rimba post-merge hook (or a prior cleanup run) was interrupted mid-rm: a
# worktree still registered in .git but whose directory is gone from disk.
# State, not event: robust to external kills that also took down this script
# on a prior run, not just to a timeout caught by Block B on this run.
HOOK_INTERRUPTED=0
while IFS= read -r _line; do
  case "$_line" in
    "worktree "*) _wt=${_line#worktree }; [ -d "$_wt" ] || HOOK_INTERRUPTED=1 ;;
  esac
done < <(git worktree list --porcelain)

if [ "$HOOK_INTERRUPTED" -eq 1 ]; then
  if [ "$TIMED_OUT" -eq 1 ]; then
    echo "sync-and-verify: internal timeout (${SYNC_TIMEOUT}s) interrupted the post-merge hook — partial worktree deletion detected. Recover: run 'git worktree prune' from the main repo, then delete the stale branch." >&2
  else
    echo "sync-and-verify: partial worktree deletion detected (a registered worktree is missing on disk — a prior cleanup was likely interrupted). Recover: run 'git worktree prune' from the main repo." >&2
  fi
fi

printf 'WORKTREE_GONE=%s\n' "$WORKTREE_GONE"
printf 'HOOK_INTERRUPTED=%s\n' "$HOOK_INTERRUPTED"
