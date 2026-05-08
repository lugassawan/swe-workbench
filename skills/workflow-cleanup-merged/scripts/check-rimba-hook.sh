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
[ -x "$HOOK_FILE" ] && grep -qE '^[^#]*rimba clean --merged --force' "$HOOK_FILE" \
  && RIMBA_HOOK_ACTIVE=1

printf 'RIMBA_HOOK_ACTIVE=%s\n' "$RIMBA_HOOK_ACTIVE"
