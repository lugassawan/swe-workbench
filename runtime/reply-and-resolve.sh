#!/usr/bin/env bash
# Reply to a PR review thread (REST) and optionally resolve it (GraphQL).
# Usage: reply-and-resolve.sh <owner> <repo> <pr> <comment_databaseid> <thread_id> <reply_body>
# Empty reply_body skips the reply; empty thread_id skips the resolve
# (ADDRESSED -> both, CLARIFIED -> reply only, DEFERRED -> neither).
set -euo pipefail
OWNER="${1:?}"; REPO="${2:?}"; PR="${3:?}"
COMMENT_DATABASEID="${4:-}"; THREAD_ID="${5:-}"; REPLY_BODY="${6:-}"
if [ -n "$REPLY_BODY" ]; then
  gh api "repos/${OWNER}/${REPO}/pulls/${PR}/comments/${COMMENT_DATABASEID}/replies" -F body="$REPLY_BODY"
fi
if [ -n "$THREAD_ID" ]; then
  gh api graphql -F threadId="$THREAD_ID" -f query='
    mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) { thread { id isResolved } } }'
fi
