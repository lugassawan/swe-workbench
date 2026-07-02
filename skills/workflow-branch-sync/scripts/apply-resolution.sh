#!/usr/bin/env bash
# Applies a user-intent conflict resolution to one file, translating the
# mine/main side into git's --ours/--theirs — inverted under rebase, where
# --ours is the rebase target (default branch) and --theirs is the replayed
# commit (your branch), the opposite of merge.
# Usage: apply-resolution.sh <file> <mine|main> <merge|rebase>
# Stdout contract: GIT_SIDE=ours|theirs
# Exit non-zero on bad args or if git checkout/add fails.
set -euo pipefail

FILE="${1:?Usage: apply-resolution.sh <file> <mine|main> <merge|rebase>}"
SIDE="${2:?Usage: apply-resolution.sh <file> <mine|main> <merge|rebase>}"
OP="${3:?Usage: apply-resolution.sh <file> <mine|main> <merge|rebase>}"

case "$SIDE" in
  mine|main) ;;
  *)
    echo "apply-resolution: SIDE must be 'mine' or 'main', got '$SIDE'" >&2
    exit 1
    ;;
esac

case "$OP" in
  merge|rebase) ;;
  *)
    echo "apply-resolution: OP must be 'merge' or 'rebase', got '$OP'" >&2
    exit 1
    ;;
esac

if [ "$OP" = "merge" ]; then
  [ "$SIDE" = "mine" ] && GIT_SIDE="ours" || GIT_SIDE="theirs"
else
  [ "$SIDE" = "mine" ] && GIT_SIDE="theirs" || GIT_SIDE="ours"
fi

git checkout "--$GIT_SIDE" -- "$FILE"
git add -- "$FILE"

printf 'GIT_SIDE=%s\n' "$GIT_SIDE"
