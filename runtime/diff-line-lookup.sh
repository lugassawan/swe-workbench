#!/usr/bin/env bash
# Resolve the post-diff line number for a literal code snippet — for the GitHub
# Reviews API `line` field. Replaces hand-counting the offset from a hunk header.
# Usage: diff-line-lookup.sh <path> <pattern> [--range=<rev-range> | --staged | --stdin]
set -euo pipefail

usage() {
  if [ $# -gt 0 ]; then
    echo "swe-workbench-diff-line-lookup: $1" >&2
  fi
  echo "Usage: swe-workbench-diff-line-lookup <path> <pattern> [--range=<rev-range> | --staged | --stdin]" >&2
  exit 64
}

[ $# -ge 2 ] || usage "missing required arguments: <path> and <pattern>"

TARGET_PATH="$1"
PATTERN="$2"
shift 2

SOURCE_MODE="head"
RANGE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --range=*)
      [ "$SOURCE_MODE" = "head" ] || usage "conflicting source flags"
      RANGE="${1#--range=}"
      [ -n "$RANGE" ] || usage "--range requires a non-empty <rev-range>"
      SOURCE_MODE="range"
      ;;
    --staged)
      [ "$SOURCE_MODE" = "head" ] || usage "conflicting source flags"
      SOURCE_MODE="staged"
      ;;
    --stdin)
      [ "$SOURCE_MODE" = "head" ] || usage "conflicting source flags"
      SOURCE_MODE="stdin"
      ;;
    *)
      usage "unknown flag: $1"
      ;;
  esac
  shift
done

case "$PATTERN" in
  *$'\n'*)
    usage "pattern must not contain a newline — pass the most distinctive single line instead"
    ;;
esac

[ -n "$PATTERN" ] || usage "pattern must not be empty"

case "$SOURCE_MODE" in
  stdin)  DIFF=$(cat) ;;
  staged) DIFF=$(git diff --no-color --src-prefix=a/ --dst-prefix=b/ --cached -- "$TARGET_PATH") || usage "git diff --cached failed for '$TARGET_PATH'" ;;
  range)  DIFF=$(git diff --no-color --src-prefix=a/ --dst-prefix=b/ "$RANGE" -- "$TARGET_PATH") || usage "git diff failed for range '$RANGE' — check the rev-range is valid" ;;
  head)   DIFF=$(git diff --no-color --src-prefix=a/ --dst-prefix=b/ HEAD -- "$TARGET_PATH") || usage "git diff HEAD failed for '$TARGET_PATH'" ;;
esac

DLL_PATH="$TARGET_PATH" DLL_PATTERN="$PATTERN" awk '
BEGIN {
  path = ENVIRON["DLL_PATH"]
  pattern = ENVIRON["DLL_PATTERN"]
  in_target = 0
  in_hunk = 0
  old_line = 0
  new_line = 0
  match_count = 0
  candidates = ""
  found_context_line = -1
  found_removed_line = -1
}

/^diff --git / {
  in_target = 0
  in_hunk = 0
  next
}

!in_hunk && /^\+\+\+ / {
  hdr = $0
  sub(/^\+\+\+ /, "", hdr)
  if (hdr == "/dev/null") {
    in_target = 0
  } else {
    sub(/^b\//, "", hdr)
    in_target = (hdr == path)
  }
  next
}

in_target && /^@@ / {
  line = $0
  if (match(line, /-[0-9]+/)) old_line = substr(line, RSTART + 1, RLENGTH - 1) + 0
  if (match(line, /\+[0-9]+/)) new_line = substr(line, RSTART + 1, RLENGTH - 1) + 0
  in_hunk = 1
  next
}

in_target && in_hunk {
  first = substr($0, 1, 1)
  if (first == "\\") { next }
  content = substr($0, 2)
  if (first == "+") {
    if (index(content, pattern) > 0) {
      match_count++
      candidates = candidates path ":" new_line "\n"
    }
    new_line++
  } else if (first == " ") {
    if (found_context_line == -1 && index(content, pattern) > 0) {
      found_context_line = new_line
    }
    new_line++
    old_line++
  } else if (first == "-") {
    if (found_removed_line == -1 && index(content, pattern) > 0) {
      found_removed_line = old_line
    }
    old_line++
  }
  next
}

END {
  if (match_count == 1) {
    printf "%s", candidates
    exit 0
  } else if (match_count > 1) {
    printf "Error: pattern matches %d added lines; narrow it.\n", match_count > "/dev/stderr"
    n = split(candidates, arr, "\n")
    for (i = 1; i <= n; i++) {
      if (arr[i] != "") printf "  %s\n", arr[i] > "/dev/stderr"
    }
    exit 2
  } else if (found_context_line != -1) {
    printf "Error: pattern not found on any added line; found on context line %s:%d (unchanged, not part of this diff).\n", path, found_context_line > "/dev/stderr"
    exit 1
  } else if (found_removed_line != -1) {
    printf "Error: pattern not found on any added line; found on removed line %s:%d (deleted by this diff).\n", path, found_removed_line > "/dev/stderr"
    exit 1
  } else {
    printf "Error: pattern not found in diff for %s.\n", path > "/dev/stderr"
    exit 1
  }
}
' <<<"$DIFF"
