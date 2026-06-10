#!/usr/bin/env bash
# clean-state-files.sh <file>...
#
# Delete named workflow state files, but only after proving each is a
# sanctioned /tmp artifact.  Exits 1 (never silently) when any safety
# check fails.  Called on the success path by workflow skills to remove
# per-invocation state files under /tmp/.
#
# Safety checks (ALL must pass for each argument):
#   1. Argument is non-empty, absolute, and contains no ".." segment.
#   2. Argument is a regular file, or does not exist (rm -f is idempotent).
#      Must NOT be a directory or other non-regular-file type.
#   3. Path is under one of the sanctioned tmp locations:
#        /tmp/swe-workbench-pr-review/<file>
#        /tmp/swe-workbench-address-feedback/<file>
#      OR basename matches ^(capture|report-issue|audit-emit|extend)- and
#      parent directory is directly /tmp.
#
# Unlike clean-ephemeral.sh (which rm -rf a worktree directory), this
# script only calls rm -f on named regular files — never recursive.
#
# Call form:
#   bash "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/scripts/clean-state-files.sh" \
#     <file1> [<file2>...] 2>/dev/null

set -euo pipefail

reject() {
  printf 'clean-state-files: %s\n' "$*" >&2
  exit 1
}

[ "$#" -gt 0 ] || reject "at least one file argument is required"

# Resolve /tmp -> /private/tmp on macOS once.
CANON_TMP=$(cd /tmp 2>/dev/null && pwd -P) || CANON_TMP="/tmp"

validate_one() {
  local TARGET="$1"

  [ -n "$TARGET" ] || reject "empty file argument"

  case "$TARGET" in
    /*) ;;
    *) reject "path must be absolute: $TARGET" ;;
  esac

  if printf '%s' "$TARGET" | grep -qE '(^|/)\.\.(\/|$)'; then
    reject "path contains '..' traversal: $TARGET"
  fi

  # Reject directories and other non-regular files; absent files are allowed (rm -f is idempotent).
  if [ -e "$TARGET" ] && [ ! -f "$TARGET" ]; then
    reject "path is not a regular file: $TARGET"
  fi

  local parent base canon_parent canon_target
  parent="$(dirname "$TARGET")"
  base="$(basename "$TARGET")"
  canon_parent=$(cd "$parent" 2>/dev/null && pwd -P) || canon_parent="$parent"
  canon_target="${canon_parent}/${base}"

  # Path A: under a sanctioned /tmp/swe-workbench-* directory (canonical path).
  case "$canon_target" in
    "${CANON_TMP}/swe-workbench-pr-review/"*)        return 0 ;;
    "${CANON_TMP}/swe-workbench-address-feedback/"*) return 0 ;;
  esac
  # Fallback: raw /tmp path (handles missing parent dir when macOS /tmp -> /private/tmp).
  case "$TARGET" in
    "/tmp/swe-workbench-pr-review/"*)        return 0 ;;
    "/tmp/swe-workbench-address-feedback/"*) return 0 ;;
  esac

  # Path B: basename matches a known single-file-writer pattern, parent is /tmp.
  if [ "$canon_parent" = "$CANON_TMP" ] || [ "$parent" = "/tmp" ]; then
    if printf '%s' "$base" | grep -qE '^(capture|report-issue|audit-emit|extend)-'; then
      return 0
    fi
  fi

  reject "path did not pass sanctioned-location check: $TARGET"
}

for arg in "$@"; do
  validate_one "$arg"
done

rm -f -- "$@"
