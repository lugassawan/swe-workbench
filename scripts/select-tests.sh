#!/usr/bin/env bash
# Prints the tests/test_*.py files that cover what changed between two commits, one per line.
# A changed test selects itself; any other changed file selects the tests that mention its name.
#
# Usage: scripts/select-tests.sh [--base REF] [--head REF] [--list-changed]
#   --base REF       compare from REF (default: merge-base of --head and origin/main, else main)
#   --head REF       compare to REF (default: HEAD)
#   --list-changed   print the changed paths instead of the selected tests
#
# A name-mention heuristic, not a dependency graph: CI runs the full suite as the backstop.
set -euo pipefail

if [ $# -ge 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
  exit 0
fi

base=""
head="HEAD"
list_changed=0
while [ $# -gt 0 ]; do
  case "$1" in
    --base) base="${2:?--base needs a ref}"; shift 2 ;;
    --head) head="${2:?--head needs a ref}"; shift 2 ;;
    --list-changed) list_changed=1; shift ;;
    *) echo "select-tests: unknown argument: $1" >&2; exit 64 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"

if [ -z "$base" ]; then
  for ref in origin/main main; do
    if base=$(git merge-base "$head" "$ref" 2>/dev/null) && [ -n "$base" ]; then
      break
    fi
    base=""
  done
fi
if [ -z "$base" ] || ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
  echo "select-tests: no usable base commit to compare against" >&2
  exit 0
fi

changed=$(git diff --name-only "$base" "$head")
if [ "$list_changed" -eq 1 ]; then
  printf '%s\n' "$changed"
  exit 0
fi

selected=""
shared=0
while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    tests/test_*.py)
      [ -f "$path" ] && selected="${selected}"$'\n'"${path}"
      continue
      ;;
    tests/conftest.py | tests/helpers.py | tests/pi_guard_fixtures.py | tests/*requirements* | pyproject.toml)
      shared=1
      continue
      ;;
  esac
  name="${path##*/}"
  # generic file names would match everything; use the parent dir or the full path instead
  case "$name" in
    SKILL.md) needle="$(basename "$(dirname "$path")")" ;;
    README.md | package.json | package-lock.json | plugin.json | marketplace.json | settings.json)
      needle="$path"
      ;;
    *) needle="$name" ;;
  esac
  hits=$(grep -l -F -- "$needle" tests/test_*.py 2>/dev/null || true)
  [ -z "$hits" ] || selected="${selected}"$'\n'"${hits}"
  case "$name" in
    *.py)
      stem="${name%.py}"
      hits=$(grep -lE "^[[:space:]]*(import|from)[[:space:]]+${stem}([[:space:]]|\$|\.)" tests/test_*.py 2>/dev/null || true)
      [ -z "$hits" ] || selected="${selected}"$'\n'"${hits}"
      ;;
  esac
done <<EOF
$changed
EOF

if [ "$shared" -eq 1 ]; then
  echo "select-tests: shared test infrastructure changed — run scripts/test-all.sh for the full suite" >&2
fi
printf '%s\n' "$selected" | sed '/^$/d' | sort -u
