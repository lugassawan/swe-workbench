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

## Input contract

The posting mechanism itself lives in `bin/swe-workbench-pr-review-submit` — it validates every
field below and aborts (`workflow-pr-review-post: invalid payload — <field> <problem>. Refusing
to post.`, non-zero exit, before any network call) on a violation, so this table documents the
contract callers must satisfy, not a check this skill performs itself.

| Field | CLI flag | Requirement |
|---|---|---|
| `PR` | `--pr` | non-empty, matches `[1-9][0-9]*` |
| `OWNER`/`REPO` | `--repo owner/repo` | non-empty |
| `HEAD_SHA` | `--head-sha` | 40-char git SHA |
| `BASE` | `--base` | non-empty |
| `DECISION` | `--decision` | `APPROVE` or `COMMENT` |
| `BYLINE` | `--byline` | non-empty, **identity-only** markdown clause (e.g. `_Reviewed by \`reviewer\`_`) — must NOT embed the swe-workbench remark or `posted`/`deduped` counts; the script appends both (remark only on a confirmed-public repo — fail-safe omits it on private/unknown) |
| `BLOCKING_SCOPE` | `--blocking-scope` | `NONE` / `OUT-OF-DIFF-ONLY` / `IN-DIFF`, default `IN-DIFF` (fail-safe). Set from the reviewer agent's in-diff/out-of-diff classification; the specialist PR-mode sub-flow omits it, so the diff-scoping flip never fires there — deliberate, not an oversight. |
| `CURRENT_USER`/`AUTHOR_LOGIN` | `--current-user`/`--author-login` | optional; empty = identity unknown (self-review flip and auto-approve both stay suppressed — never guesses) |
| `FINDINGS[]` row | `--findings-json <path\|->` (JSON array) | each row `{severity, body, anchor}`; `anchor=inline` rows also carry `{path, line}`. **Inline comment bodies must NOT contain the byline/remark** in any form — a `comments[]` body is `finding.body` verbatim; the byline/remark is a review-level concern the script builds once. |
| `CALLER_TAG` | `--caller-tag` | non-empty — `general`, `followup`, or the specialist mode name; also scopes an optional `--debug-dir` dump (`<tag>-threads.json` / `<tag>-payload.json`) so two callers reviewing the same PR concurrently never collide |

## Post

```bash
command -v swe-workbench-pr-review-submit >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
eval "$(swe-workbench-pr-review-submit \
  --repo "$OWNER/$REPO" --pr "$PR" --head-sha "$HEAD_SHA" --base "$BASE" \
  --decision "$DECISION" --byline "$BYLINE" --caller-tag "$CALLER_TAG" \
  --findings-json "$FINDINGS_JSON_PATH" --blocking-scope "$BLOCKING_SCOPE" \
  --current-user "$CURRENT_USER" --author-login "$AUTHOR_LOGIN")"
```

This one call replaces the fetch/dedup/pre-validate/assemble/self-review-gate/atomic-submit
mechanism previously written out as bash+jq prose here: fetches existing review threads
(paginated), dedups inline findings against them (±5-line fuzzy match + Jaccard ≥ 0.4 body
overlap, any author, unresolved only) with a 👍 reaction on match, pre-validates surviving inline
anchors against the PR diff — demoting out-of-diff/ambiguous rows into a single pr-level batch
comment rather than dropping them — applies the self-review + diff-scoping decision flip, and
submits: atomically when possible (one `comments[]` POST), with a single bounded retry on a
confirmed 422 (re-fetches HEAD via `headRefOid`, genuinely re-validates/demotes, retries once) and
a per-comment fallback otherwise. The core never submits APPROVE on self-review — GitHub blocks a
self-authored `APPROVE` outright, so `EVENT` is forced to `COMMENT` regardless of `$DECISION`. A
network/5xx failure is **never** blind-retried (no idempotency
key for this endpoint); the script confirms via a read-your-write check before conceding to the
fallback. The core owns the ` [swe-workbench](https://github.com/lugassawan/swe-workbench)` remark
(appended to the byline on a confirmed-public repo only) — callers' own `BYLINE` stays
identity-only and never embeds it. See `bin/swe-workbench-pr-review-submit`'s module docstring for
the full rationale, and
[`docs/gh-api-field-flags.md`](../../docs/gh-api-field-flags.md) /
[`docs/shell-echo-vs-printf.md`](../../docs/shell-echo-vs-printf.md) for the shell-side pitfalls
building the payload in Python sidesteps entirely.

`eval` sets `POSTED_INLINE`, `POSTED_PR_LEVEL`, `DEDUPED`, `SUBMITTED`, `EVENT`, `DECISION`,
`REVIEW_URL` — every value `printf %q`-quoted. Finding bodies are never echoed to stdout, so a
body containing shell metacharacters can never inject into the `eval`.

## Step 5 — Address-feedback CTA (conditional)

Call `AskUserQuestion` when the review produced something actionable — `DECISION = COMMENT`, OR `posted > 0`, OR `deduped > 0` (`posted = POSTED_INLINE + POSTED_PR_LEVEL`):

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

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| A pre-validated finding goes out-of-diff at post time, or the atomic POST 422s outright (stale `commit_id`) | `SUBMITTED=false` after a `422`-bearing response | Demoted to the pr-level batch (never dropped); retried once against a re-fetched HEAD, then falls back to the per-comment path |
| Atomic POST fails on network/5xx | Non-422 failure | Never blind-retried; confirmed via a read-your-write check before falling back |
| Self-review, or `comments[]` is empty (`N == 0`) | `CURRENT_USER == AUTHOR_LOGIN`, or no inline survivors after dedup + pre-validate | Self-review always submits `EVENT=COMMENT`. Empty: submits the plain decision review directly, no atomic POST attempted. |
| All findings dedup-matched, or the pr-level batch post fails | `POSTED_INLINE=0` and `POSTED_PR_LEVEL=0`, or a `[warn]` on stderr | Submit proceeds regardless — inline findings still post/submit; a failed pr-level batch is logged, not retried |

## Common mistakes

| Mistake | Fix |
|---|---|
| Re-deriving the fetch/dedup/pre-validate/submit mechanism inline instead of calling `swe-workbench-pr-review-submit` | The script is the single source of truth for posting mechanics — every caller invokes it the same way |
| Passing a byline that embeds the swe-workbench remark or `posted`/`deduped` counts | The script appends both once it knows the real counts and confirmed repo visibility — an embedded byline fails input-contract validation |
| Assuming pr-level findings dedup across runs | They don't (known v1 limitation) — re-running the same specialist mode on an unchanged PR re-posts the batch |
| Reading `$POSTED_INLINE`/etc. before checking `$SUBMITTED` | A `false` `SUBMITTED` means the fallback exhausted its options; treat the counts as best-effort in that case |
