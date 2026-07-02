#!/usr/bin/env bash
# Applies a user-intent conflict resolution to one file, translating the
# mine/main side into git's --ours/--theirs — inverted under rebase, where
# --ours is the rebase target (default branch) and --theirs is the replayed
# commit (your branch), the opposite of merge.
#
# Handles delete/modify conflicts: if the chosen side deleted the file, there
# is no blob for `git checkout --ours/--theirs` to check out ("does not have
# our/their version") — resolve that case as `git rm` instead, which is the
# correct outcome for having chosen the side that deleted the file.
#
# Usage: apply-resolution.sh <file> <mine|main> <merge|rebase>
# Stdout contract: GIT_SIDE=ours|theirs
# Exit non-zero on bad args or if git checkout/add/rm fails for any reason
# other than the chosen side lacking a blob (delete/modify conflict).
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

CHECKOUT_ERR=$(git checkout "--$GIT_SIDE" -- "$FILE" 2>&1) && git add -- "$FILE" || {
  case "$CHECKOUT_ERR" in
    *"does not have our version"*|*"does not have their version"*)
      git rm -- "$FILE" >/dev/null
      ;;
    *)
      echo "apply-resolution: $CHECKOUT_ERR" >&2
      exit 1
      ;;
  esac
}

printf 'GIT_SIDE=%s\n' "$GIT_SIDE"
