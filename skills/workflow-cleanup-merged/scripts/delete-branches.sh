#!/usr/bin/env bash
# Deletes the local and remote copies of a merged feature branch.
# Usage: delete-branches.sh <headRefName>
# Stdout contract: LOCAL_DELETED=0|1 then REMOTE_DELETED=0|1
#   1 = this script performed the delete; 0 = already gone (idempotent).
# Exit non-zero only if $MAIN_REPO cannot be resolved.
set -euo pipefail

HEAD_REF="${1:?Usage: delete-branches.sh <headRefName>}"

# Block A: derive $MAIN_REPO and anchor cwd
MAIN_REPO=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
[ -n "${MAIN_REPO:-}" ] || { echo "delete-branches: could not resolve main repo path — aborting" >&2; exit 1; }
cd "$MAIN_REPO"

# Block B: delete local branch if present (capital -D: squash-merged branches
# are not merge ancestors of main so lowercase -d would refuse)
LOCAL_DELETED=0
if git rev-parse --verify "refs/heads/$HEAD_REF" >/dev/null 2>&1; then
  git branch -D "$HEAD_REF" >/dev/null 2>&1
  LOCAL_DELETED=1
fi

# Block C: delete remote branch (always attempted regardless of local result,
# to handle the WORKTREE_GONE=1 path where local is already gone)
REMOTE_DELETED=0
if PUSH_ERR=$(git push origin --delete "$HEAD_REF" 2>&1); then
  REMOTE_DELETED=1
else
  case "$PUSH_ERR" in
    *"remote ref does not exist"*|*"unable to delete"*|*404*)
      # Already gone — treat as success, REMOTE_DELETED stays 0
      ;;
    *)
      printf 'delete-branches: remote delete failed: %s\n' "$PUSH_ERR" >&2
      ;;
  esac
fi

printf 'LOCAL_DELETED=%s\n' "$LOCAL_DELETED"
printf 'REMOTE_DELETED=%s\n' "$REMOTE_DELETED"
