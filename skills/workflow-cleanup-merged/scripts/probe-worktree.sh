#!/usr/bin/env bash
# Locates the worktree for a given branch and runs dirty/unpushed safety checks.
# Usage: probe-worktree.sh <head_ref>
# Stdout contract: WORKTREE=<path|empty>\nDIRTY=N\nUNPUSHED=N
set -euo pipefail

HEAD_REF="${1:?Usage: probe-worktree.sh <head_ref>}"

# Use awk string comparison (-v) to avoid regex metachar injection from HEAD_REF
WORKTREE=$(git worktree list --porcelain \
  | awk -v ref="branch refs/heads/$HEAD_REF" '/^worktree /{p=$2} $0 == ref {print p; exit}')

if [ -n "${WORKTREE:-}" ]; then
  DIRTY=$(git -C "$WORKTREE" status --porcelain | grep -c . || echo 0)
  UNPUSHED=$(git -C "$WORKTREE" log "@{upstream}..HEAD" --oneline 2>/dev/null | grep -c . || echo 0)
else
  DIRTY=0
  UNPUSHED=0
fi

# %q shell-quotes WORKTREE so eval in the caller handles paths with spaces safely
printf 'WORKTREE=%q\nDIRTY=%s\nUNPUSHED=%s\n' "${WORKTREE:-}" "$DIRTY" "$UNPUSHED"
