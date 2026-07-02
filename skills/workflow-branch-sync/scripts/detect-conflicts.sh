#!/usr/bin/env bash
# Detects whether a merge or rebase is currently in progress and lists any
# unmerged (conflicted) file paths.
# Usage: detect-conflicts.sh
# Stdout contract:
#   line 1: OPERATION=merge|rebase|none   (eval-safe KEY=VALUE)
#   remaining lines: one unmerged file path per line, raw — do not eval,
#                     iterate with `while IFS= read -r file`.
# Exit non-zero only if the cwd is not inside a git work tree.
set -euo pipefail

_GIT_DIR=$(git rev-parse --git-dir 2>/dev/null) \
  || { echo "detect-conflicts: not inside a git work tree" >&2; exit 1; }

if [ -f "$_GIT_DIR/MERGE_HEAD" ]; then
  OPERATION=merge
elif [ -d "$_GIT_DIR/rebase-merge" ] || [ -d "$_GIT_DIR/rebase-apply" ]; then
  OPERATION=rebase
else
  OPERATION=none
fi

printf 'OPERATION=%s\n' "$OPERATION"

git diff --name-only --diff-filter=U
