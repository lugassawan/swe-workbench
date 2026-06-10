#!/usr/bin/env bash
# Fetch a PR's metadata JSON; exit 1 if the PR is missing or unreadable.
# Usage: fetch-pr.sh <PR> <out_path> <json_fields>
set -euo pipefail
PR="${1:?Usage: fetch-pr.sh <PR> <out_path> <json_fields>}"
OUT="${2:?Usage: fetch-pr.sh <PR> <out_path> <json_fields>}"
FIELDS="${3:?Usage: fetch-pr.sh <PR> <out_path> <json_fields>}"
mkdir -p "$(dirname "$OUT")"
gh pr view "$PR" --json "$FIELDS" > "$OUT"
[ -s "$OUT" ] || { echo "PR #$PR not found or not accessible."; exit 1; }
