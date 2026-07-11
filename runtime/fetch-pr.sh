#!/usr/bin/env bash
# Fetch a PR's metadata JSON; exit 1 if the PR is missing or unreadable.
# Usage: fetch-pr.sh <PR> <out_path> <json_fields>
set -euo pipefail
PR="${1:?Usage: fetch-pr.sh <PR> <out_path> <json_fields>}"
OUT="${2:?Usage: fetch-pr.sh <PR> <out_path> <json_fields>}"
FIELDS="${3:?Usage: fetch-pr.sh <PR> <out_path> <json_fields>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$(dirname "$OUT")"
bash "$SCRIPT_DIR/gh-timeout.sh" pr view "$PR" --json "$FIELDS" > "$OUT" || { echo "PR #$PR not found or not accessible." >&2; exit 1; }
[ -s "$OUT" ] || { echo "PR #$PR returned empty JSON." >&2; exit 1; }
