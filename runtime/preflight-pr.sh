#!/usr/bin/env bash
# Consolidated pre-flight for PR-review workflows.
# Usage: preflight-pr.sh <PR> <out_json> [fields]
#
# Outputs KEY=VALUE lines (printf %q quoted) for eval:
#   BASE  HEAD_SHA  AUTHOR_LOGIN  OWNER  REPO  STATE
#
# title/body are NOT emitted — they are free-text and echoing them into
# eval "$(...)" enables code injection.  Read them from <out_json> with jq.
#
# Resolves sibling scripts via dirname "$0" so the script works correctly
# even when cwd is an ephemeral PR worktree (CLAUDE_PLUGIN_ROOT may be unset).
set -euo pipefail

PR="${1:?Usage: preflight-pr.sh <PR> <out_json> [fields]}"
OUT_JSON="${2:?Usage: preflight-pr.sh <PR> <out_json> [fields]}"
FIELDS="${3:-state,number,headRefName,baseRefName,headRefOid,title,body,author,reviewDecision}"

SCRIPT_DIR="$(dirname "$0")"

gh auth status >/dev/null || {
  echo "gh not authenticated. Run 'gh auth login'." >&2
  exit 1
}

bash "$SCRIPT_DIR/fetch-pr.sh" "$PR" "$OUT_JSON" "$FIELDS"

BASE=$(jq -r .baseRefName     "$OUT_JSON")
HEAD_SHA=$(jq -r .headRefOid  "$OUT_JSON")
AUTHOR_LOGIN=$(jq -r .author.login "$OUT_JSON")
STATE=$(jq -r .state          "$OUT_JSON")

OWNER=$(gh repo view --json owner -q .owner.login)
REPO=$(gh repo view --json name   -q .name)
if [ -z "$OWNER" ] || [ "$OWNER" = "null" ] || [ -z "$REPO" ] || [ "$REPO" = "null" ]; then
  echo "Could not determine base repo owner/name. Run 'gh repo view' to verify the current remote is set correctly." >&2
  exit 1
fi

printf 'BASE=%q\n'         "$BASE"
printf 'HEAD_SHA=%q\n'     "$HEAD_SHA"
printf 'AUTHOR_LOGIN=%q\n' "$AUTHOR_LOGIN"
printf 'OWNER=%q\n'        "$OWNER"
printf 'REPO=%q\n'         "$REPO"
printf 'STATE=%q\n'        "$STATE"
