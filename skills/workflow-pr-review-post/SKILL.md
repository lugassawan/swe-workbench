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
| `BYLINE` | non-empty, fully-formed markdown identity clause (e.g. `_Reviewed by \`reviewer\`_`) — **must NOT** embed `posted`/`deduped` counts; this skill appends its own stats clause in Step 4, since those counts aren't known until Step 2 runs |
| `BLOCKING_SCOPE` | one of `NONE`, `OUT-OF-DIFF-ONLY`, `IN-DIFF`; default `IN-DIFF` if the caller omits it (fail-safe) |
| `FINDINGS[]` | each row has `severity`, `body`, and `anchor ∈ {inline, pr-level}`; `anchor=inline` rows must also have `path` and `line` |
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

## Step 2 — Dedup + post

Partition `FINDINGS[]` by `anchor`.

### Inline findings (`anchor=inline`)

For each: **fuzzy-match** against fetched threads, against ANY author:
- Same `path` (exact, repo-relative).
- `|finding.line - thread.line| ≤ 5` (use `startLine` for multi-line ranges).
- Body Jaccard token overlap ≥ 0.4.
- `isResolved == false`.

**On match**: skip posting. If `$CURRENT_USER` has not already 👍'd (check `reactions.nodes[].user.login`; use `reactions(first: 20, ...)` — 5 truncates busy threads), add a 👍 to the thread head (first comment's `id`):

```bash
gh api graphql -F subjectId="$THREAD_HEAD_ID" -f query='
  mutation($subjectId: ID!) {
    addReaction(input: {subjectId: $subjectId, content: THUMBS_UP}) { reaction { id } }
  }'
```

**On no match**: post a new inline comment via REST (supports `line=` directly):

```bash
gh api "repos/${OWNER}/${REPO}/pulls/${PR}/comments" \
  -f body="$BODY" \
  -F path="$REPO_PATH" \
  -F line="$LINE" \
  -F side=RIGHT \
  -F commit_id="$HEAD_SHA"
```

**Why `-f body=`, not `-F body=`:** a finding body may start with `@author…`; `-F` would silently
`@`-expand it into a file read. See [`docs/gh-api-field-flags.md`](../../docs/gh-api-field-flags.md).
**Spot-check** any body sourced from a file: `gh api <endpoint>/{id} -q '.body'`.

Track counts: `posted_inline=N`, `deduped=M`. Initialise `DEFERRED_INFORMATIONAL=""` before the loop. On HTTP 422: out-of-diff informational findings → `DEFERRED_INFORMATIONAL` (not stale-SHA; expected for context-line refs); in-diff findings on 422 → skip/log, stale-SHA counted (see Failure modes).

### PR-level findings (`anchor=pr-level`)

No thread to dedup against — `dependency-auditor` rows (no `File:Line`) and any inline row whose line fell out-of-diff both land here. Batch ALL pr-level findings into **one** general PR comment (not deduped across runs — see Common mistakes):

```bash
if gh pr comment "$PR" --body "$PR_LEVEL_BODY"; then
  posted_pr_level=$PR_LEVEL_FINDING_COUNT   # count each batched finding individually even though they share one API call
else
  posted_pr_level=0
  echo "[warn] gh pr comment failed — pr-level batch of $PR_LEVEL_FINDING_COUNT finding(s) NOT posted." >&2
fi
```

Only issue this call when at least one pr-level finding exists. `posted_pr_level` must be set **after** the call, gated on its exit status — never increment it unconditionally before knowing whether the post actually landed, or a failed batch gets reported as posted in Step 4's byline and wrongly fires Step 5's CTA on a `posted > 0` that corresponds to nothing on the PR. Maintain `posted=$((posted_inline + posted_pr_level))` as the combined total used by the CTA/suppression outcome-axis checks below (Steps 4–5); the byline in Step 4 reports the split counts separately so a dependency-mode run (pr-level only) doesn't misreport itself as having posted inline comments.

## Step 3 — Self-review gate + diff-scoping flip

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
```

Identity unknown (`CURRENT_USER` or `AUTHOR_LOGIN` empty) → `IS_SELF_REVIEW=false` but `IDENTITY_KNOWN=false` suppresses the flip (fail-safe: never auto-approve when authorship can't be verified).

## Step 4 — Submit

The review body is lean by design: decision line + byline (+ optional informational notes) only — findings already posted in Step 2 must NOT be restated here. `$BYLINE` is the caller's identity clause only (e.g. `_Reviewed by \`reviewer\` ([swe-workbench](https://github.com/lugassawan/swe-workbench))._`) — it cannot include `posted`/`deduped` counts, since those are only known after Step 2 runs here in the core. This skill appends the stats clause itself:

```bash
BYLINE_FULL="${BYLINE} Posted ${posted_inline} inline comment(s) and ${posted_pr_level} PR-level note(s), deduped ${deduped}."
INFORMATIONAL_SECTION=""
[ -n "$DEFERRED_INFORMATIONAL" ] && INFORMATIONAL_SECTION=$(printf '\n\n### Informational (out-of-diff)\n\n%s\n' "$DEFERRED_INFORMATIONAL")
if [ "$IS_SELF_REVIEW" = false ]; then
  SUMMARY=$(printf '**Review Decision: %s**\n\n%s%s\n' "$DECISION" "$BYLINE_FULL" "$INFORMATIONAL_SECTION")
else
  SUMMARY=""
fi
```

Submit when `IS_SELF_REVIEW = false` (GitHub blocks self-approval):
- `APPROVE` → `gh pr review "$PR" --approve --body "$SUMMARY"`
- `COMMENT` → `gh pr review "$PR" --comment --body "$SUMMARY"`

Skip when `IS_SELF_REVIEW = true`. **Never** use `--request-changes`. Findings already posted inline/PR-level in Step 2 must NOT be restated in `$SUMMARY`.

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

This skill never touches the caller's own worktree or preflight state files (e.g. `${PR}.json`, `${PR}-followup.json`) — those stay the caller's responsibility, cleaned up alongside its own worktree teardown after this skill returns.

## Dedup contract (inline only)

A new finding `(path, line, body)` matches an existing thread `T` IFF: `T.path == finding.path` (exact) AND `|T.line - finding.line| ≤ 5` (or `T.startLine`) AND Jaccard overlap ≥ 0.4 AND `T.isResolved == false`. Match against ANY author. On match, skip posting AND add 👍 if not already reacted.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| Comment-post returns 422 (line out of range) | HTTP 422 | In-diff finding: skip, log "skipped (line out of range)", count toward stale-SHA. Out-of-diff informational: append to `DEFERRED_INFORMATIONAL`; do **not** count toward stale-SHA. |
| All in-diff POSTs returned 422 (stale `commit_id`) | `posted == 0` AND every in-diff finding 422'd | Re-fetch `HEAD_SHA` via `gh pr view "$PR" --json headRefOid -q .headRefOid` and retry once. If still failing, abort with "HEAD_SHA mismatch — PR updated mid-review". |
| All findings dedup-matched | `posted == 0` | Submit with body noting "no new findings — all previously raised". Decision unaffected. |
| GraphQL pagination needed (PR > 100 threads) | `hasNextPage == true` | Loop with `after: endCursor`. Known v1 limit if not hit/implemented. |
| `gh pr comment` fails for a pr-level batch | Non-zero exit | Log and continue — inline findings from the same run must still post/submit; do not abort the whole flow over the pr-level fallback. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Dedup pr-level findings against `reviewThreads` | `reviewThreads` only covers inline comment threads; a pr-level finding has no `path`/`line` to match against. Batch and post once; re-running the same specialist mode on an unchanged PR will re-post the batch (known v1 limitation — no pr-level dedup yet). |
| `-F body="$BODY"` on a finding that starts with `@` → silent `@`-file-expansion | Use `-f body=` (raw). See [`docs/gh-api-field-flags.md`](../../docs/gh-api-field-flags.md). |
| Apply the diff-scoping flip on self-review or unknown identity | Gated on `IS_SELF_REVIEW=false` AND `IDENTITY_KNOWN=true`. Either false → no flip. |
| Reuse the caller's own state-file names for the threads cache | This skill owns `${PR}-post-threads-${CALLER_TAG}.json` specifically so it never collides with a caller's `${PR}.json`/`${PR}-threads.json`/`${PR}-followup*.json`, nor with another caller's own tagged threads cache for the same PR. |
| Set `posted_pr_level` before checking whether `gh pr comment` succeeded | Gate the assignment on the call's exit status — a failed batch must leave `posted_pr_level=0`, not the finding count, or the byline/CTA misreport what was actually posted. |
| Restate posted findings in the review `$SUMMARY` body | Findings live in inline comments / the pr-level batch comment; the summary is decision + byline (+ informational) only. |
| Block on this skill's own cleanup before returning control | Step 6 reap is foreground (fast, single small file) — unlike worktree teardown, which the caller backgrounds separately. |
| Report a dependency-mode (pr-level-only) run as "posted N inline comments" | The byline reports `posted_inline` and `posted_pr_level` separately — a run with zero inline posts must not claim it posted inline comments just because `posted` (the combined total) is non-zero. |
| Assume `$_RT` is inherited from the caller's Step 1 | This skill is its own skill boundary, not a `source`d shell fragment — re-derive `_RT="${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}"` at the top of Step 6. |
