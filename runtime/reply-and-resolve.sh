#!/usr/bin/env bash
# Reply to a PR review thread (REST) and optionally resolve it (GraphQL).
# Usage: reply-and-resolve.sh <owner> <repo> <pr> <comment_databaseid> <thread_id> <reply_body> [kind]
# Empty reply_body skips the reply (COMMENT_DATABASEID is then ignored); empty thread_id skips the resolve
# (ADDRESSED -> both, CLARIFIED -> reply only, DEFERRED -> neither).
# kind (optional, default "review"): the existing thread-reply + resolve behavior above.
# "issue" posts REPLY_BODY to the PR's top-level conversation (issues/{pr}/comments) instead — used
# for PR-level comments, which have no thread to resolve. COMMENT_DATABASEID/THREAD_ID are ignored.
set -euo pipefail
# Fast-exit for DEFERRED: nothing to do when both reply and resolve are suppressed.
if [ -z "${6:-}" ] && [ -z "${5:-}" ]; then exit 0; fi
OWNER="${1:?}"; REPO="${2:?}"; PR="${3:?}"
COMMENT_DATABASEID="${4:-}"; THREAD_ID="${5:-}"; REPLY_BODY="${6:-}"
KIND="${7:-review}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
case "$KIND" in
  issue)
    [ -n "$REPLY_BODY" ] || exit 0
    # -f (raw), not -F: an @author-prefixed body would be @-file-expanded by -F. See docs/gh-api-field-flags.md
    bash "$SCRIPT_DIR/gh-timeout.sh" api "repos/${OWNER}/${REPO}/issues/${PR}/comments" -f body="$REPLY_BODY"
    exit 0 ;;
  review) : ;;
  *) echo "reply-and-resolve: unknown KIND '$KIND'" >&2; exit 1 ;;
esac
if [ -n "$REPLY_BODY" ]; then
  [ -n "$COMMENT_DATABASEID" ] || { echo "reply-and-resolve: REPLY_BODY set but COMMENT_DATABASEID is empty" >&2; exit 1; }
  # -f (raw), not -F: an @author-prefixed body would be @-file-expanded by -F. See docs/gh-api-field-flags.md
  bash "$SCRIPT_DIR/gh-timeout.sh" api "repos/${OWNER}/${REPO}/pulls/${PR}/comments/${COMMENT_DATABASEID}/replies" -f body="$REPLY_BODY"
fi
if [ -n "$THREAD_ID" ]; then
  bash "$SCRIPT_DIR/gh-timeout.sh" api graphql -F threadId="$THREAD_ID" -f query='
    mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) { thread { id isResolved } } }'
fi
