#!/usr/bin/env bash
# Anchors cwd to the main repo, syncs local main, and checks whether the
# rimba post-merge hook already cleaned up the given branch.
# Usage: sync-and-verify.sh <head_ref>
# Stdout contract: WORKTREE_GONE=0|1
# Exit non-zero only if $MAIN_REPO cannot be resolved.
set -euo pipefail

HEAD_REF="${1:?Usage: sync-and-verify.sh <head_ref>}"

# Block A: derive $MAIN_REPO and anchor cwd
MAIN_REPO=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
[ -n "${MAIN_REPO:-}" ] || { echo "sync-and-verify: could not resolve main repo path — aborting" >&2; exit 1; }
cd "$MAIN_REPO"

# Block B: sync local main (best-effort — failure warns, does not abort)
(git checkout main && git pull --ff-only origin main) \
  || echo "sync-main: best-effort failed — reconcile main manually" >&2

# Block C: verification gate — check whether hook already cleaned up
# Use awk string comparison (-v) to avoid regex metachar injection from HEAD_REF
WORKTREE_FOUND=$(git worktree list --porcelain \
  | awk -v ref="branch refs/heads/$HEAD_REF" '$0 == ref {print 1; exit}')
if git rev-parse --verify "refs/heads/$HEAD_REF" 2>/dev/null; then
  BRANCH_FOUND=1
else
  BRANCH_FOUND=
fi

WORKTREE_GONE=0
[ -z "${WORKTREE_FOUND:-}" ] && [ -z "${BRANCH_FOUND:-}" ] && WORKTREE_GONE=1

printf 'WORKTREE_GONE=%s\n' "$WORKTREE_GONE"
