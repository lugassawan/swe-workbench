# Resolve review threads reference

Full mechanics for Phase 5's reply-and-resolve calls, covering both review threads
(GraphQL `resolveReviewThread`, wrapped by `swe-workbench-reply-and-resolve`) and PR-level
conversation comments (REST only — PR comments have no thread to resolve).

## Review threads

For each **ADDRESSED** or **CLARIFIED** review thread, post a reply via REST then conditionally resolve (DEFERRED threads skip this call entirely). Use `comments.nodes[0].databaseId` (the thread root comment) as `$COMMENT_DATABASEID` — replies must target the first comment in the thread, not a subsequent reply.

Reply body templates by triage classification:
- **ADDRESSED**: `"Addressed in ${FIX_SHA}: <one-line summary of fix>."` — pass both `$REPLY_BODY` and `$THREAD_ID`.
- **CLARIFIED**: free-text owner-authored reply (asked interactively) — pass `$REPLY_BODY` with empty `$THREAD_ID` (reply only, no resolve).
- **DEFERRED**: pass empty `$REPLY_BODY` and empty `$THREAD_ID` (neither reply nor resolve).
```bash
swe-workbench-reply-and-resolve \
  "$OWNER" "$REPO" "$PR" "$COMMENT_DATABASEID" "$THREAD_ID" "$REPLY_BODY"
```

## PR-level comments

For each **ADDRESSED** or **CLARIFIED** PR comment (`triage["prcomment:<id>"]`), post a reply on the PR's top-level conversation instead of a thread reply — PR comments have no thread, so resolve is always suppressed and `KIND=issue` is passed explicitly. Compose `$REPLY_BODY` as `@{comment author} re:` + a single-line blockquote of the original (first ~100 chars, newlines collapsed) + the addressed/clarified body (same wording as the review-thread templates above) + a hidden marker on its own line — `<!-- swe-workbench:handled:{comment.id} -->` — which Phase 1's dedup filter matches on re-runs (omitting it makes the comment look unhandled forever). The original comment body is attacker-controlled: extract the blockquote via `jq -r` into a shell variable (e.g. `QUOTE=$(jq -r '.[] | select(.id==ID) | .body' ... | head -c 100 | tr '\n' ' ')`) and reference `"$QUOTE"` when building `$REPLY_BODY` — never retype the raw comment text into a double-quoted bash literal, since `$(...)`/backticks in the source text would execute at assignment time. DEFERRED PR comments skip the call entirely, same as DEFERRED threads:
```bash
swe-workbench-reply-and-resolve \
  "$OWNER" "$REPO" "$PR" "" "" "$REPLY_BODY" "issue"
```
