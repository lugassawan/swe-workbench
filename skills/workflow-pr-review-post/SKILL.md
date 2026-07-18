---
name: workflow-pr-review-post
description: Posting core shared by workflow-pr-review, workflow-pr-review-followup, and the specialist /swe-workbench:review PR-mode sub-flow — takes a normalized findings/decision/byline payload, dedupes against existing review threads (±5-line fuzzy match + Jaccard ≥ 0.4), posts new inline or PR-level comments, applies the self-review + diff-scoping decision flip, and submits APPROVE or COMMENT.
orchestrator: true
---

# Workflow: PR Review — Posting Core (shared mechanism)

**Announce at start:** "I'm using the workflow-pr-review-post skill to post these findings to PR #N."

## When to invoke

- Called by `swe-workbench:workflow-pr-review` (general PR mode) after its Step 5 footer parse.
- Called by `swe-workbench:workflow-pr-review-followup` after its Step 5 footer parse.
- Called by `/swe-workbench:review <PR#> --mode <specialist>` after the user replies `post` to the confirmation prompt (specialist PR-mode sub-flow).

## When NOT to invoke

- Local-diff mode → never invoked; there is no PR to post to.
- `--mode contributor-trust` → never invoked; `contributor-auditor`'s contract is advisory-only, never posts.
- Directly by a user prompt with no pre-computed payload — this skill is pure mechanism; something upstream must have already run an auditor and derived a decision.

## Input contract (validation preamble — abort on any violation)

Before Step 1, verify every required field is present and well-formed. **Abort immediately** (print the specific missing/invalid field; do not post or submit anything) if any check fails — no compiler enforces this markdown contract, so this preamble is the only guard:

| Field | Requirement |
|---|---|
| `PR` | non-empty, matches `[1-9][0-9]*` |
| `OWNER`, `REPO` | non-empty |
| `HEAD_SHA` | non-empty (40-char git SHA) |
| `BASE` | non-empty |
| `CURRENT_USER`, `AUTHOR_LOGIN` | may be empty (identity-unknown is a valid state — see Step 3), but if provided must be plain login strings |
| `DECISION` | exactly `APPROVE` or `COMMENT` |
| `BYLINE` | non-empty, **identity-only** markdown clause (e.g. `_Reviewed by \`reviewer\`_`) — **must NOT** embed the swe-workbench remark (` ([swe-workbench](https://github.com/lugassawan/swe-workbench))`) or `posted`/`deduped` counts; this skill appends the remark conditionally (public repos only) and its own stats clause in Step 4, since repo visibility and those counts aren't known until Step 2/4 run |
| `BLOCKING_SCOPE` | one of `NONE`, `OUT-OF-DIFF-ONLY`, `IN-DIFF`; default `IN-DIFF` if the caller omits it (fail-safe). `workflow-pr-review`/`workflow-pr-review-followup` set this from the reviewer agent's own in-diff/out-of-diff classification; the specialist PR-mode sub-flow intentionally omits it (specialist auditors don't classify diff-scope), which falls back to `IN-DIFF` — the diff-scoping flip (Step 3) accordingly never fires for specialist-mode reviews. This is a deliberate divergence, not an oversight. |
| `FINDINGS[]` | each row has `severity`, `body`, and `anchor ∈ {inline, pr-level}`; `anchor=inline` rows must also have `path` and `line`. **Inline comment bodies must NOT contain the byline/remark** in any form — a `comments[]` body is `finding.body` verbatim; the byline/remark is a review-level concern built once in Step 4, never folded into a per-finding body (issue #531) |
| `CALLER_TAG` | non-empty, one of `general`, `followup`, or the specialist mode name (e.g. `security`, `dependency`) — scopes this skill's own state file so two callers reviewing the same PR concurrently never share (and can't clobber) each other's threads cache |

Abort message: `"workflow-pr-review-post: invalid payload — <field> <problem>. Refusing to post."`

## Step 1 — Fetch existing review threads

```bash
gh api graphql -F number="$PR" -F owner="$OWNER" -F repo="$REPO" -f query='
  query($owner: String!, $repo: String!, $number: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $number) {
        reviewThreads(first: 100) {
          nodes {
            id isResolved path line startLine
            comments(first: 10) {
              nodes {
                id databaseId body
                author { login }
                reactions(first: 20, content: THUMBS_UP) {
                  nodes { user { login } }
                }
              }
            }
          }
        }
      }
    }
  }' > "/tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json"
```

Pagination via `pageInfo { endCursor hasNextPage }` if a real PR exceeds 100 threads (known v1 limit — document, don't implement, unless it's actually hit).

Uses its own `${PR}-post-threads-${CALLER_TAG}.json` state file — scoped by `CALLER_TAG` so it's distinct both from any `${PR}.json`/`${PR}-threads.json`/`${PR}-followup*.json` files the caller may hold, AND from another caller's own `${PR}-post-threads-*.json` reviewing the same PR concurrently (e.g. a general review and a specialist `--mode security` review both in flight — without the tag, both would share one cache file and one run's Step 6 reap could delete the other's cache mid-flight).

## Step 2 — Dedup + pre-validate + assemble

Partition `FINDINGS[]` by `anchor`.

### Inline findings (`anchor=inline`)

For each: **fuzzy-match** against fetched threads, against ANY author:
- Same `path` (exact, repo-relative).
- `|finding.line - thread.line| ≤ 5` (use `startLine` for multi-line ranges).
- Body Jaccard token overlap ≥ 0.4.
- `isResolved == false`.

**On match**: skip posting, increment `$deduped`. If `$CURRENT_USER` has not already 👍'd (check `reactions.nodes[].user.login`; use `reactions(first: 20, ...)` — 5 truncates busy threads), add a 👍 to the thread head (first comment's `id`):

```bash
gh api graphql -F subjectId="$THREAD_HEAD_ID" -f query='
  mutation($subjectId: ID!) {
    addReaction(input: {subjectId: $subjectId, content: THUMBS_UP}) { reaction { id } }
  }'
```

**On no match**: the finding survives dedup and becomes a candidate for the pending review's `comments[]` batch, posted atomically in Step 4 (`POST .../pulls/{n}/reviews`) instead of individually here. A candidate's body is `finding.body` **verbatim** — never `$BYLINE`/`$BYLINE_FULL`/`$REMARK` concatenated in; the byline is a review-level concern built once in Step 4 (issue #531 — inline comments must never repeat it).

**Pre-validate before assembly**: the atomic Reviews API POST in Step 4 submits the whole batch in one call — one bad `(path, line)` 422s the *entire* review, and the error body carries no per-comment index to identify which row failed (an assumption to confirm on a scratch PR), so a stale or invalid line must be caught here, before it can poison the batch. Confirm each survivor's `line` lands on a `+` (added/modified) line for `path` in the diff at `$HEAD_SHA` — reuse the diff already fetched for this run, or re-fetch with `gh pr diff "$PR"`. **In-diff** → assemble into `comments[]` below. **Out-of-diff** → re-anchor the finding `pr-level` and fold it into the PR-level batch below — this is the contract's existing home for out-of-diff rows.

Assemble each in-diff survivor into the pending review's `comments[]` **JSON array** via `jq` — **not** `gh api` bracket-indexed field flags. `gh api -f "comments[0][path]=..." -f "comments[1][path]=..."` builds a JSON *object* keyed by stringified indices (`{"comments":{"0":{...},"1":{...}}}`), not an array — GitHub's Reviews API requires `comments` to be an array and rejects the object shape outright, so that syntax can never work here (verified against a live `gh` install; do not reintroduce it). `jq --arg`/`--argjson` give the same raw-string safety `-f body=` gives a scalar field: a finding body starting with `@author…` is embedded as a literal JSON string value, never file-expanded — there is no `-f`/`-F` hazard once the payload is built as real JSON rather than passed through `gh api`'s own field-flag parser (see [`docs/gh-api-field-flags.md`](../../docs/gh-api-field-flags.md)). Never string-concatenate `$BODY` directly into a JSON literal — a body containing `"` or `\` would break the JSON or inject fields; always go through `jq --arg`.

```bash
COMMENTS_JSON="[]"
for row in "${INLINE_SURVIVORS[@]}"; do   # each row resolves REPO_PATH, LINE, BODY — dedup- and diff-validated
  COMMENTS_JSON=$(jq --arg path "$REPO_PATH" --argjson line "$LINE" --arg body "$BODY" \
    '. + [{path: $path, line: $line, side: "RIGHT", body: $body}]' <<<"$COMMENTS_JSON")
done
N=$(jq 'length' <<<"$COMMENTS_JSON")
```

Freeze `N` here — the **candidate** inline count. `N` becomes `posted_inline` only once Step 4's atomic submit actually lands; a whole-review 422 can still change that outcome (see Step 4 and Failure modes).

### PR-level findings (`anchor=pr-level`)

No thread to dedup against — `dependency-auditor` rows (no `File:Line`), any inline row demoted above, and any inline row whose line fell out-of-diff both land here. Batch ALL pr-level findings (original + demoted) into **one** general PR comment (not deduped across runs — see Common mistakes), posted here in Step 2 — **before** Step 4's review submit — so `posted_pr_level` is already a landed count by the time the byline is built:

```bash
if gh pr comment "$PR" --body "$PR_LEVEL_BODY"; then
  posted_pr_level=$PR_LEVEL_FINDING_COUNT   # count each batched finding individually even though they share one API call
else
  posted_pr_level=0
  echo "[warn] gh pr comment failed — pr-level batch of $PR_LEVEL_FINDING_COUNT finding(s) NOT posted." >&2
fi
```

Only issue this call when at least one pr-level finding exists (including demoted rows). `posted_pr_level` must be set **after** the call, gated on its exit status — never increment it unconditionally before knowing whether the post actually landed, or a failed batch gets reported as posted in Step 4's byline and wrongly fires Step 5's CTA on a `posted > 0` that corresponds to nothing on the PR. Maintain `posted=$((posted_inline + posted_pr_level))` as the combined total used by the CTA/suppression outcome-axis checks below (Steps 4–5); the byline in Step 4 reports the split counts separately so a dependency-mode run (pr-level only) doesn't misreport itself as having posted inline comments.

## Step 3 — Self-review gate + diff-scoping flip + submit event

```bash
if [ -z "$CURRENT_USER" ] || [ -z "$AUTHOR_LOGIN" ]; then
  echo "[warn] IS_SELF_REVIEW: identity unknown (CURRENT_USER='$CURRENT_USER' AUTHOR_LOGIN='$AUTHOR_LOGIN'); treating as cross-author but diff-scoping flip suppressed (identity unknown)." >&2
  IS_SELF_REVIEW=false
elif [ "$CURRENT_USER" = "$AUTHOR_LOGIN" ]; then IS_SELF_REVIEW=true
else IS_SELF_REVIEW=false; fi

IDENTITY_KNOWN=$([ -n "$CURRENT_USER" ] && [ -n "$AUTHOR_LOGIN" ] && echo true || echo false)
if [ "$DECISION" = "COMMENT" ] && [ "$BLOCKING_SCOPE" = "OUT-OF-DIFF-ONLY" ] \
   && [ "$IS_SELF_REVIEW" = false ] && [ "$IDENTITY_KNOWN" = true ]; then
  DECISION=APPROVE
fi

if [ "$IS_SELF_REVIEW" = true ]; then EVENT=COMMENT; else EVENT="$DECISION"; fi
```

Identity unknown (`CURRENT_USER` or `AUTHOR_LOGIN` empty) → `IS_SELF_REVIEW=false` but `IDENTITY_KNOWN=false` suppresses the flip (fail-safe: never auto-approve when authorship can't be verified).

`$EVENT` — not `$DECISION` — is what Step 4 actually submits to the Reviews API. GitHub blocks a self-authored `APPROVE` outright but allows a self-authored `COMMENT`, so on self-review `EVENT` is forced to `COMMENT` regardless of `$DECISION` (e.g. a clean scan with no findings still yields `DECISION=APPROVE`) — this replaces the pre-#531 behavior of skipping submit entirely on self-review, which under the atomic posting model would have silently dropped every inline comment along with it. The core never submits `APPROVE` on self-review.

## Step 4 — Submit

The review body is lean by design: decision line + byline (+ optional informational notes) only — findings already posted in Step 2 must NOT be restated here. On self-review the decision line is omitted (the run always submits `EVENT=COMMENT`, never the pre-flip `$DECISION`, which could misleadingly read `APPROVE`) but the byline/stats clause still appears — self-review no longer skips submit outright (see Step 3). `$BYLINE` is the caller's identity clause only (e.g. `` _Reviewed by `reviewer`_ ``) — it must NOT embed the swe-workbench remark, and it cannot include `posted`/`deduped` counts, since those are only known after Step 2 runs here in the core. This skill appends both:

```bash
IS_PRIVATE=$(gh repo view "${OWNER}/${REPO}" --json isPrivate -q '.isPrivate' 2>/dev/null)
REMARK=""
[ "$IS_PRIVATE" = "false" ] && REMARK=" ([swe-workbench](https://github.com/lugassawan/swe-workbench))"
```

`IS_PRIVATE` is gated on a **confirmed** `"false"` (public) result — an empty/errored lookup (permission issue, transient failure) or an explicit `"true"` both leave `REMARK` empty. This is deliberately fail-safe: never advertise the tool on a repo whose visibility couldn't be confirmed public.

The lean body above has no out-of-diff carve-out section — that mechanism belonged to the pre-#499 single-loop design, where in-diff and out-of-diff findings shared one posting path. This refactor's `anchor` partition (Step 2) already gives out-of-diff findings their own dedicated path (the pr-level batch comment), so there is nothing left to defer into the review body.

**Build the pre-submit body from `$N`, not `$posted_inline`.** The atomic POST's own `body=$SUMMARY` field has to describe what it is *about to* post, and `$posted_inline` is not assigned until after that same POST completes — referencing it here would embed an unset/empty count into the review body itself. Atomicity makes the `$N` assumption safe: either all `$N` comments land together with this exact body, or the POST fails outright and the fallback below rebuilds `$SUMMARY` from the real landed count before its own separate submit:

```bash
BYLINE_FULL="${BYLINE}${REMARK}. Posted ${N} inline comment(s) and ${posted_pr_level} PR-level note(s), deduped ${deduped}."
if [ "$IS_SELF_REVIEW" = true ]; then SUMMARY=$(printf '%s\n' "$BYLINE_FULL")
else SUMMARY=$(printf '**Review Decision: %s**\n\n%s\n' "$DECISION" "$BYLINE_FULL"); fi
```

**Submit — atomic path first, when `N > 0`:**

```bash
if [ "$N" -gt 0 ]; then
  PAYLOAD=$(jq -n --arg commit_id "$HEAD_SHA" --arg event "$EVENT" --arg body "$SUMMARY" --argjson comments "$COMMENTS_JSON" \
    '{commit_id: $commit_id, event: $event, body: $body, comments: $comments}')
  RESP=$(gh api --method POST "repos/${OWNER}/${REPO}/pulls/${PR}/reviews" --input - <<<"$PAYLOAD" 2>&1)
  if [ $? -eq 0 ]; then
    posted_inline=$N; SUBMITTED=true
  elif echo "$RESP" | grep -q '422'; then
    # Stale commit_id, or a line pre-validate missed — re-fetch HEAD and
    # GENUINELY re-validate/reassemble (do NOT resubmit $COMMENTS_JSON
    # unchanged); demote anything newly out-of-diff to a pr-level comment.
    HEAD_SHA=$(gh pr view "$PR" --json headRefOid -q .headRefOid)
    COMMENTS_JSON="[]"; STILL_IN_DIFF=()
    for row in "${INLINE_SURVIVORS[@]}"; do   # each row resolves REPO_PATH, LINE, BODY
      if line_is_in_diff "$REPO_PATH" "$LINE" "$HEAD_SHA"; then   # same predicate as Step 2's pre-validate pass
        COMMENTS_JSON=$(jq --arg path "$REPO_PATH" --argjson line "$LINE" --arg body "$BODY" \
          '. + [{path: $path, line: $line, side: "RIGHT", body: $body}]' <<<"$COMMENTS_JSON")
        STILL_IN_DIFF+=("$row")
      else
        gh pr comment "$PR" --body "$BODY" && posted_pr_level=$((posted_pr_level + 1))
      fi
    done
    INLINE_SURVIVORS=("${STILL_IN_DIFF[@]}"); N=$(jq 'length' <<<"$COMMENTS_JSON")
    BYLINE_FULL="${BYLINE}${REMARK}. Posted ${N} inline comment(s) and ${posted_pr_level} PR-level note(s), deduped ${deduped}."
    if [ "$IS_SELF_REVIEW" = true ]; then SUMMARY=$(printf '%s\n' "$BYLINE_FULL")
    else SUMMARY=$(printf '**Review Decision: %s**\n\n%s\n' "$DECISION" "$BYLINE_FULL"); fi

    PAYLOAD=$(jq -n --arg commit_id "$HEAD_SHA" --arg event "$EVENT" --arg body "$SUMMARY" --argjson comments "$COMMENTS_JSON" \
      '{commit_id: $commit_id, event: $event, body: $body, comments: $comments}')
    RESP2=$(gh api --method POST "repos/${OWNER}/${REPO}/pulls/${PR}/reviews" --input - <<<"$PAYLOAD" 2>&1)
    [ $? -eq 0 ] && { posted_inline=$N; SUBMITTED=true; }
  fi
  # Any other failure (network, 5xx) is NOT retried — never blind-retry a POST
  # with no idempotency key; SUBMITTED stays unset, falls through below.
fi

if [ "${SUBMITTED:-false}" != true ]; then
  # Reached when N=0 (nothing to batch — today's plain submit) OR the atomic
  # POST 422'd twice OR failed on network/5xx — model-A per-comment fallback.
  posted_inline=0
  for row in "${INLINE_SURVIVORS[@]}"; do   # empty loop when N=0; each row resolves REPO_PATH, LINE, BODY
    if gh api "repos/${OWNER}/${REPO}/pulls/${PR}/comments" \
         -f body="$BODY" \
         -F path="$REPO_PATH" \
         -F line="$LINE" \
         -F side=RIGHT \
         -F commit_id="$HEAD_SHA"; then
      posted_inline=$((posted_inline + 1))
    else
      # Never drop a finding silently on a fallback POST failure — demote to
      # a follow-up pr-level note (same treatment an out-of-diff finding gets).
      echo "[warn] individual comment POST failed for $REPO_PATH:$LINE — demoting to pr-level." >&2
      gh pr comment "$PR" --body "$BODY" && posted_pr_level=$((posted_pr_level + 1))
    fi
  done
  BYLINE_FULL="${BYLINE}${REMARK}. Posted ${posted_inline} inline comment(s) and ${posted_pr_level} PR-level note(s), deduped ${deduped}."
  if [ "$IS_SELF_REVIEW" = true ]; then SUMMARY=$(printf '%s\n' "$BYLINE_FULL")
  else SUMMARY=$(printf '**Review Decision: %s**\n\n%s\n' "$DECISION" "$BYLINE_FULL"); fi
  if [ "$IS_SELF_REVIEW" = false ] && [ "$EVENT" = "APPROVE" ]; then gh pr review "$PR" --approve --body "$SUMMARY"
  else gh pr review "$PR" --comment --body "$SUMMARY"; fi
fi
```

In the fallback block, `$posted_inline` is read *after* the loop assigns it — no ordering hazard, since `$SUMMARY` here feeds the fallback's own `gh pr review` submit, never the already-sent atomic POST. When `N=0` the loop body never executes and `posted_inline` stays `0`, degenerating exactly to the pre-#531 plain submit — the empty-`comments[]` case is a fall-through, not a special case.

**Never** use `--request-changes`. **Never** blind-retry the atomic POST on a network/5xx failure — there is no idempotency key for this endpoint, so a retried call that actually landed the first time double-posts every comment; the single retry above is scoped to a confirmed 422 only. Findings already posted inline/PR-level in Step 2 must NOT be restated in `$SUMMARY`.

## Step 5 — Address-feedback CTA (conditional)

Call `AskUserQuestion` when the review produced something actionable — `DECISION = COMMENT`, OR `posted > 0`, OR `deduped > 0`:

```json
{
  "questions": [{
    "question": "Want me to help address this feedback? Start /swe-workbench:address-feedback <N>?",
    "header": "Next step",
    "multiSelect": false,
    "options": [
      { "label": "Yes — address feedback", "description": "Starts /swe-workbench:address-feedback <N> to drive fixes end-to-end." },
      { "label": "No thanks",              "description": "Stay here; no further action." }
    ]
  }]
}
```

Substitute the real PR number for `<N>`. On `Yes — address feedback` → invoke `/swe-workbench:address-feedback <N>`. On `No thanks` (or anything else) → no further action. Suppress silently when `DECISION = APPROVE` and `posted = 0` and `deduped = 0` (post-flip evaluation — a clean approval with nothing posted/deduped has nothing to address). Identity does NOT gate the CTA.

## Step 6 — State reap

Foreground — failures surface (no `2>/dev/null` or `|| true`). This skill is invoked as its own skill boundary, not a `source`d fragment of the caller's shell — `$_RT` from a caller's Step 1 is not inherited, so re-derive it here:

```bash
_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"
bash "$_RT/runtime/clean-state-files.sh" "/tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json"
[ -e "/tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json" ] \
  && echo "⚠ state file NOT reaped: /tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json" >&2 \
  || echo "✓ state file reaped: /tmp/swe-workbench-pr-review/${PR}-post-threads-${CALLER_TAG}.json"
```

This skill never touches the caller's own worktree or preflight state files (e.g. `${PR}.json`, `${PR}-followup.json`) — those stay the caller's responsibility, cleaned up alongside its own worktree teardown after this skill returns. (Dedup contract: see the fuzzy-match rule in Step 2 — same `path`, `|line delta| ≤ 5`, Jaccard ≥ 0.4, unresolved, any author.)

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| A pre-validated finding is out-of-diff at post time (`HEAD_SHA` advanced since the diff-scoping scan) | Line-in-diff check fails during Step 2 assembly | Demote to the pr-level batch — never drop a finding silently. |
| Atomic review POST returns 422 — stale `commit_id`, since every row in `comments[]` was pre-validated in-diff before assembly | `gh api` non-zero exit, response contains `422` | Re-fetch `HEAD_SHA` (`gh pr view "$PR" --json headRefOid -q .headRefOid`), re-run pre-validate/assemble, retry the atomic POST **once**. Still failing → fall back to model-A per-comment posting (rebuild `$SUMMARY` from the actual landed count, submit the event via `gh pr review`). |
| Atomic review POST fails on network/5xx | Non-422 failure | **Never** blind-retry — no idempotency key for this endpoint, so a retried call that already landed double-posts every comment. Fall straight to the model-A fallback. |
| `comments[]` is empty (`N == 0`) | No inline survivors after dedup + pre-validate | Fall through to `gh pr review --approve\|--comment` directly — no atomic POST attempted (the existing pre-#531 path, unchanged). |
| Self-review (`IS_SELF_REVIEW=true`) | `CURRENT_USER == AUTHOR_LOGIN` | Submit with `EVENT=COMMENT` regardless of `$DECISION` — GitHub blocks self-`APPROVE` but allows self-`COMMENT`, so this run's inline/pr-level comments still land instead of the whole submit being skipped. |
| All findings dedup-matched | `posted == 0` | Submit with body noting "no new findings — all previously raised". Decision unaffected. |
| GraphQL pagination needed (PR > 100 threads) | `hasNextPage == true` | Loop with `after: endCursor`. Known v1 limit if not hit/implemented. |
| `gh pr comment` fails for a pr-level batch | Non-zero exit | Log and continue — inline findings from the same run must still post/submit; do not abort the whole flow over the pr-level fallback. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Dedup pr-level findings against `reviewThreads` | `reviewThreads` only covers inline comment threads; a pr-level finding has no `path`/`line` to match against. Batch and post once; re-running the same specialist mode on an unchanged PR will re-post the batch (known v1 limitation — no pr-level dedup yet). |
| Assemble `comments[]` via `gh api` bracket-indexed field flags, or string-concatenate `$BODY` into a JSON literal | Bracket indices (`comments[0][path]=...`) build a stringified-key *object*, not an array — GitHub's Reviews API rejects it. String concatenation breaks on `"`/`\`. Build `comments[]` as real JSON via `jq --arg`/`--argjson` and post with `gh api --input -`. |
| `-F body=` on the fallback POST for a finding that starts with `@` → silent `@`-file-expansion | Use `-f body="$BODY"` (raw). See [`docs/gh-api-field-flags.md`](../../docs/gh-api-field-flags.md). |
| Concatenate `$BYLINE`/`$BYLINE_FULL`/`$REMARK` into a `comments[]` body | Inline comment bodies are `finding.body` verbatim — the byline/remark is a Step 4, review-level concern only (issue #531). |
| Post inline comments individually while assembling `comments[]` | Assemble the whole batch and submit it atomically via `POST .../pulls/{n}/reviews`; per-comment posting is the model-A fallback, reachable only after a confirmed double-422 (or when `N=0`). |
| Apply the diff-scoping flip on self-review or unknown identity | Gated on `IS_SELF_REVIEW=false` AND `IDENTITY_KNOWN=true`. Either false → no flip. |
| Reuse the caller's own state-file names for the threads cache | This skill owns `${PR}-post-threads-${CALLER_TAG}.json` specifically so it never collides with a caller's `${PR}.json`/`${PR}-threads.json`/`${PR}-followup*.json`, nor with another caller's own tagged threads cache for the same PR. |
| Set `posted_pr_level` before checking whether `gh pr comment` succeeded | Gate the assignment on the call's exit status — a failed batch must leave `posted_pr_level=0`, not the finding count, or the byline/CTA misreport what was actually posted. |
| Restate posted findings in the review `$SUMMARY` body | Findings live in inline comments / the pr-level batch comment; the summary is decision + byline (+ informational) only. |
| Block on this skill's own cleanup before returning control | Step 6 reap is foreground (fast, single small file) — unlike worktree teardown, which the caller backgrounds separately. |
| Report a dependency-mode (pr-level-only) run as "posted N inline comments" | The byline reports `posted_inline` and `posted_pr_level` separately — a run with zero inline posts must not claim it posted inline comments just because `posted` (the combined total) is non-zero. |
| Assume `$_RT` is inherited from the caller's Step 1 | This skill is its own skill boundary, not a `source`d shell fragment — re-derive `_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"` at the top of Step 6. |
