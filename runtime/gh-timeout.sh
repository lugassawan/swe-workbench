#!/usr/bin/env bash
# Run `gh` under a per-call timeout so a stalled GitHub API response can't hang
# a PR-helper script. Override the deadline (seconds) with GH_TIMEOUT_SECS (default 60).
# Degrades to plain `gh` when neither `timeout` nor `gtimeout` (macOS/coreutils) is present.
# On timeout, exits 124 and prints a diagnostic to stderr so a stall is not misreported
# by a caller (e.g. fetch-pr.sh's "PR not found" branch).
set -euo pipefail

secs="${GH_TIMEOUT_SECS:-60}"
# Require >=1: a 0 duration means "disable the timer" to GNU timeout/gtimeout, which would
# silently re-introduce an unbounded gh call — treat it the same as any other malformed override.
[[ "$secs" =~ ^[1-9][0-9]*$ ]] || secs=60

if command -v timeout >/dev/null 2>&1; then
  timeout_bin=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  timeout_bin=gtimeout
else
  exec gh "$@"   # no timeout binary available — degrade to unbounded gh
fi

rc=0
"$timeout_bin" -k 5 "$secs" gh "$@" || rc=$?
if [ "$rc" -eq 124 ]; then
  echo "gh-timeout: 'gh $*' exceeded ${secs}s deadline (GH_TIMEOUT_SECS) and was terminated." >&2
fi
exit "$rc"
