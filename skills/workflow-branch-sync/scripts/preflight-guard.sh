#!/usr/bin/env bash
# Detects branch-sync preflight state — reports only. Refusal logic (on the
# default branch, detached HEAD) lives in the calling skill, which reads
# these flags and decides whether to abort.
# Usage: preflight-guard.sh
# Stdout contract: CURRENT_BRANCH=<name>
#                   DEFAULT_BRANCH=<name>
#                   IS_DEFAULT=0|1
#                   DETACHED=0|1
#                   DIRTY=<count>
# Exit non-zero only if the cwd is not inside a git work tree.
set -euo pipefail

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "preflight-guard: not inside a git work tree" >&2; exit 1; }

SYMBOLIC=$(git symbolic-ref -q HEAD 2>/dev/null || true)
if [ -z "$SYMBOLIC" ]; then
  DETACHED=1
  CURRENT_BRANCH=$(git rev-parse --short HEAD)
else
  DETACHED=0
  CURRENT_BRANCH="${SYMBOLIC#refs/heads/}"
fi

# Detect the default branch — never hardcode "main": gh first, then the
# origin/HEAD symref, then a last-resort literal fallback.
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null \
  || git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' \
  || echo main)

IS_DEFAULT=0
[ "$DETACHED" = "0" ] && [ "$CURRENT_BRANCH" = "$DEFAULT_BRANCH" ] && IS_DEFAULT=1

DIRTY=$(git status --porcelain | wc -l | tr -d ' ')

# %q-quote the two string fields — git branch names may legally contain
# shell metacharacters ($, `, ;, etc; see git-check-ref-format), and this
# output is eval'd by the caller. Numeric fields need no quoting.
printf 'CURRENT_BRANCH=%q\n' "$CURRENT_BRANCH"
printf 'DEFAULT_BRANCH=%q\n' "$DEFAULT_BRANCH"
printf 'IS_DEFAULT=%s\n' "$IS_DEFAULT"
printf 'DETACHED=%s\n' "$DETACHED"
printf 'DIRTY=%s\n' "$DIRTY"
