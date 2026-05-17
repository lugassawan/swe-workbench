#!/usr/bin/env bash
# PreToolUse:Bash guard — block destructive commands and short-circuit safe ones.
#
# Blocks:
#   - rm -rf against /, /*, ~, $HOME, /Users[/<user>], /home[/<user>]
#   - git push --force / -f to main/master
#   - git reset --hard on main/master/release/*
#
# Short-circuits (exit 0, no greps) for commands that contain neither "rm" nor
# "git". This is the common case (ls, cat, echo, make, npm, …) and removes the
# per-call grep tax flagged in #233.
#
# Out of scope: ${HOME} brace-form; ANSI-C $'...' quoting; path normalization via .. traversal.

set -u

if ! cmd=$(jq -r '.tool_input.command // ""'); then
  echo 'bash_guard: jq parse error — blocking by default' >&2
  exit 2
fi

case "$cmd" in
  rm\ *|*\ rm\ *|*\(*rm\ *|*git*) ;;
  *)                              exit 0 ;;
esac

# Strip quotes and subshell parens so they cannot mask the rm command or path.
norm=$(printf '%s' "$cmd" | tr -d "'\"()")

# shellcheck disable=SC2016  # $HOME in single quotes is intentional: matches literal text, not the shell variable
# [rR] covers both -rf and -Rf (BSD/macOS rm accepts -R as synonym for -r).
if echo "$norm" | grep -Eq \
   '(^|[[:space:]])rm[[:space:]]+-[a-zA-Z]*[rR][a-zA-Z]*[fF]?[[:space:]]+(/(\*|[[:space:]]|$)|(~|\$HOME)(/[^[:space:]]*)?([[:space:]]|$)|(/Users|/home)(/[^/[:space:]]+)?([[:space:]]|/|$))'; then
  echo 'BLOCKED: destructive rm against root or home' >&2
  exit 2
fi

if echo "$norm" | grep -Eq 'git[[:space:]]+push.*(--force([[:space:]]|$)|(^|[[:space:]])-f([[:space:]]|$))' \
   && echo "$norm" | grep -Eq '(^|[[:space:]]|:)(main|master)([[:space:]]|:|$)'; then
  echo 'BLOCKED: force push to main/master' >&2
  exit 2
fi

if echo "$norm" | grep -Eq 'git[[:space:]]+reset[[:space:]]+--hard'; then
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
  case "$branch" in
    main|master|release/*)
      echo "BLOCKED: git reset --hard on protected branch '$branch'" >&2
      exit 2
      ;;
  esac
fi

exit 0
