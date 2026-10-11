#!/usr/bin/env bash
# Runs the test suite (or the given pytest paths/args) politely on a shared machine: workers
# are capped, the run is niced, and a machine-wide lock makes concurrent worktrees queue.
#
# Usage: scripts/test-all.sh [--workers N] [--no-lock] [pytest args or paths...]
#   --workers N   parallel workers (default 3, or $SWE_WORKBENCH_TEST_WORKERS); 1 = serial
#   --no-lock     skip the queue (small, bounded runs such as the pre-push subset)
#
# Parallelism needs pytest-xdist (`pip install pytest-xdist`); without it the run is serial.
# $SWE_WORKBENCH_TEST_LOCK_TIMEOUT bounds the wait for the lock (seconds, default 1800).
set -uo pipefail

if [ $# -ge 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
  exit 0
fi

workers="${SWE_WORKBENCH_TEST_WORKERS:-3}"
use_lock=1
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --workers) workers="${2:?--workers needs a number}"; shift 2 ;;
    --no-lock) use_lock=0; shift ;;
    --) shift; args+=("$@"); break ;;
    *) args+=("$1"); shift ;;
  esac
done
case "$workers" in
  '' | *[!0-9]*) echo "test-all: --workers must be a number, got '${workers}'" >&2; exit 64 ;;
esac

cd "$(dirname "$0")/.." || exit 1

LOCK="${TMPDIR:-/tmp}/swe-workbench-test-all.lock"
held=0
# shellcheck disable=SC2329 # invoked via the EXIT trap
release() {
  [ "$held" -eq 1 ] && rm -rf "$LOCK"
  return 0
}

acquire() {
  local waited=0 limit="${SWE_WORKBENCH_TEST_LOCK_TIMEOUT:-1800}" holder
  while ! mkdir "$LOCK" 2>/dev/null; do
    holder=$(cat "$LOCK/pid" 2>/dev/null || true)
    if [ -z "$holder" ]; then
      sleep 1 # the holder may still be writing its pid
      holder=$(cat "$LOCK/pid" 2>/dev/null || true)
    fi
    if [ -z "$holder" ] || ! kill -0 "$holder" 2>/dev/null; then
      rm -rf "$LOCK" # stale: the holder is gone
      continue
    fi
    if [ "$waited" -ge "$limit" ]; then
      echo "test-all: gave up waiting ${limit}s for another test run (pid ${holder})" >&2
      return 75
    fi
    [ "$waited" -ne 0 ] || echo "test-all: waiting for another test run (pid ${holder}) ..." >&2
    sleep 2
    waited=$((waited + 2))
  done
  held=1
  printf '%s\n' "$$" >"$LOCK/pid"
}

trap release EXIT
trap 'exit 130' INT TERM

if [ "$use_lock" -eq 1 ]; then
  acquire || exit $?
fi

cmd=(python3 -m pytest)
if [ "$workers" -gt 1 ]; then
  if python3 -c 'import xdist' 2>/dev/null; then
    cmd+=(-n "$workers" --dist loadfile)
  else
    echo "test-all: pytest-xdist not installed — running serially (pip install pytest-xdist)" >&2
  fi
fi
[ "${#args[@]}" -gt 0 ] || args=(tests/)

if command -v nice >/dev/null 2>&1; then
  cmd=(nice -n 10 "${cmd[@]}")
fi
"${cmd[@]}" "${args[@]}"
exit $?
