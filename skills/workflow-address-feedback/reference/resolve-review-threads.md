# Resolve review threads reference

Full mechanics for Phase 5's reply-and-resolve calls, covering both review threads
(GraphQL `resolveReviewThread`, wrapped by `swe-workbench-reply-and-resolve`) and PR-level
conversation comments (REST only — PR comments have no thread to resolve).

## Review threads

For each **ADDRESSED**, **CLARIFIED**, or **DEFERRED** review thread, post a reply via REST then resolve — all three dispositions resolve the thread; only a thread the owner truly left untouched (Q-quit mid-triage) has no call at all. Use `comments.nodes[0].databaseId` (the thread root comment) as `$COMMENT_DATABASEID` — replies must target the first comment in the thread, not a subsequent reply.

Reply body templates by triage classification:
- **ADDRESSED**: `"Addressed in ${FIX_SHA}: <one-line summary of fix>."` — pass both `$REPLY_BODY` and `$THREAD_ID`.
- **CLARIFIED**: free-text owner-authored reply (asked interactively), defaulting to `"Acknowledged."` when the owner doesn't type one — pass both `$REPLY_BODY` and `$THREAD_ID` (reply + resolve). The default matters here specifically: `$THREAD_ID` is always non-empty for CLARIFIED, so an empty `$REPLY_BODY` would otherwise resolve the thread with no reply posted at all — a silent close with no audit trail.
- **DEFERRED**: free-text owner-authored reply (asked interactively, same as CLARIFIED), defaulting to `"Acknowledged — deferring for now."` when the owner doesn't type one — pass both `$REPLY_BODY` and `$THREAD_ID` (reply + resolve).
```bash
swe-workbench-reply-and-resolve \
  "$OWNER" "$REPO" "$PR" "$COMMENT_DATABASEID" "$THREAD_ID" "$REPLY_BODY"
```

## PR-level comments

For each **ADDRESSED** or **CLARIFIED** projected PR feedback item (`triage[.triage_key]`), post a new top-level conversation comment (`KIND=issue`, empty comment/thread ids — `.parent_comment_id` is identity context for the marker, not a REST reply target, since PR comments have no thread to reply into) and compose `$REPLY_BODY` as `@{author} re:` + a single-line blockquote of the extracted `.body` (first ~100 chars, newlines collapsed) + the addressed/clarified body (same wording as the review-thread templates above) + `.handled_marker` verbatim on its own line. A split finding's marker is `<!-- swe-workbench:handled:<comment-id>:finding:<finding-id> -->`; a legacy item keeps `<!-- swe-workbench:handled:<comment-id> -->`. The extracted body is attacker-controlled: extract the blockquote via `jq -r` into a shell variable and reference `"$QUOTE"` when building `$REPLY_BODY` — never retype it into a double-quoted bash literal, since `$(...)`/backticks in the source text would execute at assignment time. DEFERRED PR feedback items skip the call entirely — unlike DEFERRED review threads (see `## Review threads` above), PR comments have no thread to resolve, so DEFERRED here has nothing to reply with either:
```bash
swe-workbench-reply-and-resolve \
  "$OWNER" "$REPO" "$PR" "" "" "$REPLY_BODY" "issue"
```
