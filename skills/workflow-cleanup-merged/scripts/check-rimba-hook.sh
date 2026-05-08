#!/usr/bin/env bash
# Checks whether the rimba post-merge hook is installed and active.
# Stdout contract: RIMBA_HOOK_ACTIVE=0|1
# Exit non-zero only if $MAIN_REPO cannot be resolved.
set -euo pipefail

MAIN_REPO=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
[ -n "${MAIN_REPO:-}" ] || { echo "check-rimba-hook: could not resolve main repo path" >&2; exit 1; }

HOOKS_DIR=$(git -C "$MAIN_REPO" config --get core.hooksPath 2>/dev/null || echo "$MAIN_REPO/.git/hooks")
case "$HOOKS_DIR" in
  /*) ;;
  *) HOOKS_DIR="$MAIN_REPO/$HOOKS_DIR" ;;
esac

HOOK_FILE="$HOOKS_DIR/post-merge"
RIMBA_HOOK_ACTIVE=0
# Use if/fi so set -e doesn't fire when grep finds no match (grep exits 1 on no-match)
if [ -x "$HOOK_FILE" ] && grep -qE '^[^#]*rimba clean --merged --force' "$HOOK_FILE" 2>/dev/null; then
  RIMBA_HOOK_ACTIVE=1
fi

printf 'RIMBA_HOOK_ACTIVE=%s\n' "$RIMBA_HOOK_ACTIVE"
