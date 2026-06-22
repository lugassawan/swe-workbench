#!/usr/bin/env bash
# Apply a revised title and/or body to an existing PR (address-feedback Phase 6 drift sync).
# Usage: sync-pr-metadata.sh <pr> <new_title> <body_file>
# Empty new_title skips --title; empty body_file skips --body-file.
set -euo pipefail
PR="${1:?sync-pr-metadata: PR number required}"
NEW_TITLE="${2:-}"; BODY_FILE="${3:-}"
args=()
[ -n "$NEW_TITLE" ] && args+=(--title "$NEW_TITLE")
if [ -n "$BODY_FILE" ]; then
  [ -f "$BODY_FILE" ] || { echo "sync-pr-metadata: body file not found: $BODY_FILE" >&2; exit 1; }
  args+=(--body-file "$BODY_FILE")
fi
[ ${#args[@]} -gt 0 ] || { echo "sync-pr-metadata: nothing to update (no title, no body)" >&2; exit 1; }
gh pr edit "$PR" "${args[@]}"
