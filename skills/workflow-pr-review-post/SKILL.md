---
name: workflow-pr-review-post
description: Posting core shared by workflow-pr-review and the specialist /swe-workbench:review PR-mode sub-flow — takes a findings/decision/byline payload, dedupes by stable key and fuzzy match (±5-line, Jaccard ≥ 0.4) against threads and earlier reviews, posts one review of inline and PR-level findings (skipped if unchanged), applies the self-review + diff-scoping flip, submits APPROVE or COMMENT.
orchestrator: true
---

# Workflow: PR Review — Posting Core (shared mechanism)

**Announce at start:** "I'm using the workflow-pr-review-post skill to post these findings to PR #N."

## When to invoke

- Called by `swe-workbench:workflow-pr-review` (first-pass or followup mode) after its Step 5 footer parse.
- Called by `/swe-workbench:review <PR#> --mode <specialist>` after the user replies `post` to the confirmation prompt (specialist PR-mode sub-flow).

## When NOT to invoke

- Local-diff mode → never invoked; there is no PR to post to.
- `--mode contributor-trust` → never invoked; `swe-workbench:contributor-auditor`'s contract is advisory-only, never posts.
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
| `FINDINGS[]` row | `--findings-json <path\|->` (JSON array) | each row `{severity, issue, why, fix, anchor}` plus optional `category`; `anchor=inline` rows also carry `{path, line}`, `anchor=pr-level` rows may carry `path` (and `line`, only with `path`) so the headline can locate them. **The script renders the comment body** from these fields (`**<Sev>**[ · <Category>][ · \`path:line\` (pr-level only)] — <issue>`, then `**Why it matters:** <why>` and `**Suggested fix:** <fix>` as separate paragraphs) — callers never pass `body`; a row that does is rejected. `issue`/`why`/`fix` are required non-empty strings; `issue`, `severity` and `category` are single-line, `why`/`fix` may span lines (a value that opens with a code fence, e.g. a ` ```suggestion ` block, is rendered on its own paragraph so GitHub still treats it as a suggestion); `path` must be single-line with no backticks, and a `pr-level` `line` is valid only alongside a `path` — omit both when unknown rather than passing a range or blank. **Inline comment bodies must NOT contain the byline/remark** in any form, so no field may embed it — it is a review-level concern the script builds once. |
| `CALLER_TAG` | `--caller-tag` | non-empty — `general`, `followup`, or the specialist mode name; also scopes an optional `--debug-dir` dump (`<tag>-threads.json` / `<tag>-payload.json`) so two callers reviewing the same PR concurrently never collide |
| `SCOPE_SLUG` | — (builds `--retry-state`) | non-empty owner-repo slug the caller already resolved with `swe-workbench-repo-scope`; this skill derives `RETRY_STATE="/tmp/swe-workbench-pr-review/${SCOPE_SLUG}-${PR}-${CALLER_TAG}-submit-retry.json"` from it, so two repositories' same-numbered PRs — and two callers (first-pass, followup, a specialist) on one PR — never share or clobber a retry file |
| `APPROVE_OVER_OPEN_THREADS` | `--approve-over-open-threads` | optional; empty = no override. When non-empty: a single line, ≤200 chars, must not embed the swe-workbench remark — validated by the script, not this skill |

## Post

```bash
command -v swe-workbench-pr-review-submit >/dev/null 2>&1 && command -v swe-workbench-result-check >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
RETRY_STATE="/tmp/swe-workbench-pr-review/${SCOPE_SLUG}-${PR}-${CALLER_TAG}-submit-retry.json"
RESULT=$(swe-workbench-pr-review-submit \
  --repo "$OWNER/$REPO" --pr "$PR" --head-sha "$HEAD_SHA" --base "$BASE" \
  --decision "$DECISION" --byline "$BYLINE" --caller-tag "$CALLER_TAG" \
  --findings-json "$FINDINGS_JSON_PATH" --blocking-scope "$BLOCKING_SCOPE" \
  --current-user "$CURRENT_USER" --author-login "$AUTHOR_LOGIN" \
  --approve-over-open-threads "$APPROVE_OVER_OPEN_THREADS" \
  --retry-state "$RETRY_STATE" \
  | swe-workbench-result-check swb.pr-review-submit/1) || exit 1
```

This one call replaces the fetch/dedup/pre-validate/assemble/self-review-gate/submit mechanism
previously written out as bash+jq prose here, and it delivers a run as **one review**:

- **Dedup.** Every finding carries a stable key (path + the text of its anchor line + normalized
  content, written as a trailing `finding-key:v1` marker line) that survives line shifts and an
  inline→PR-level demotion. A finding is dropped when its key already appears in the current
  user's own earlier bodies — any thread (resolved, unresolved or outdated), earlier review
  bodies, legacy issue-comment batches — or twice in the same payload; keys in anyone else's
  bodies are ignored. Inline findings that match no key then go through the fuzzy match (±5-line +
  Jaccard ≥ 0.4 overlap of the comment text with its headline and labels stripped, any author,
  unresolved threads only), and a 👍 reaction goes only on a live (unresolved, current) match.
  Known limits: PR-level rows (including demoted ones) match earlier posts by exact key only — a
  reworded out-of-diff finding counts as new; and the key has no occurrence index, so the same
  finding on two lines that read identically (two `except Exception:` lines) shares one key. A
  carried-over row that a reworded fresh row matches (same path, ±5 lines, Jaccard ≥ 0.4) is dropped.
- **No-op skip.** When the current user's standing decision (their latest approved /
  changes-requested / dismissed review, else COMMENT if they only ever commented) equals the event
  this run would submit, and nothing new or carried over survives dedup (so it holds only while the
  reviewer's output is byte-stable or inline-only: a reworded PR-level finding counts as new), the run makes **zero
  mutations** — no review, reaction or comment — and reports `.data.skipped_reason = "unchanged"`.
  A dismissed review never equals anything, so a run after a dismissal always posts; neither does
  an approval given on an older commit than the head being reviewed, so a new push is re-approved.
  Known limit: after an approval, a run that resolves to `COMMENT` (for example `APPROVE` downgraded
  by open threads) never matches the standing approval, so each rerun posts another comment review.
- **One payload.** Surviving inline anchors are pre-validated against the PR diff; out-of-diff or
  ambiguous rows are demoted to PR-level, never dropped. The inline comments, the summary and every
  PR-level row (as an ascending-ID batch after the summary, up to 50 rows / ~60,000 characters) go
  out in a single `POST .../pulls/{n}/reviews`. Only the overflow beyond that budget is posted
  afterwards as issue-comment batches — the one allowed second mutation. Every body carries a
  provenance marker: each batch begins `<!-- swe-workbench:review-findings -->` and every finding
  `<!-- swe-workbench:review-finding:<positive-integer> -->`; address-feedback uses them to split a
  valid batch, whether it sits in a review body or an issue comment, into finding-level triage
  items.
- **Failure ladder, no per-comment fallback.** Every payload is validated before it is sent. A
  confirmed 422 re-fetches HEAD and the diff, demotes whatever is now out-of-diff into the body and
  retries once; a second 422 demotes every inline row into the body for a final body-only POST. If
  the head moved while the review ran, the retry is submitted as `COMMENT` (and `.data.event` says
  so) — code the reviewer never saw is never approved. A
  network/5xx failure is **never** blind-retried: every review body carries a fresh random run
  marker, and the script reads the reviews back and looks for it. Found → landed. Absent (a second
  look a couple of seconds later, since a timeout or a 502/504 is when the write may still be
  completing) → the identical payload is retried once. Unreadable, or the retry fails → unconfirmed.
  A permanent client error (401/403/404 and other 4xx besides 408/422/425/429) is neither read back
  nor retried.
- **Retry file.** Rows whose delivery is unconfirmed — everything after an unconfirmed review, or
  only the overflow rows whose comment batch failed — are written to `$RETRY_STATE` (atomic, mode
  0600) and merged into the next run for the same head and caller; a merged row that landed after
  all is pruned by the key dedup. Carried rows from a `COMMENT` run never ride in an `APPROVE` (the
  rerun is clamped to `COMMENT`), at most 500 rows are carried (the rest are reported), and after 5
  failed attempts the rows are dropped with a warning. The file is deleted once nothing is pending.

The core applies the self-review + diff-scoping decision flip and never submits APPROVE on self-review — GitHub
blocks a self-authored `APPROVE` outright, so `.data.event` is forced to `COMMENT` regardless of
`$DECISION`. It owns the ` [swe-workbench](https://github.com/lugassawan/swe-workbench)`
remark (appended to the byline on a confirmed-public repo only) — callers' own `BYLINE` stays
identity-only and never embeds it. See `bin/swe-workbench-pr-review-submit`'s module docstring for
the full rationale, and
[`shared/docs/gh-api-field-flags.md`](../../shared/docs/gh-api-field-flags.md) /
[`shared/docs/shell-echo-vs-printf.md`](../../shared/docs/shell-echo-vs-printf.md) for the shell-side pitfalls
building the payload in Python sidesteps entirely.

The checker validates the envelope (schema `swb.pr-review-submit/1` — see
[`shared/docs/runtime-result-contract.md`](../../shared/docs/runtime-result-contract.md)) and
re-emits it unchanged into `$RESULT`, or the pipeline fails and `|| exit 1` aborts before any
further step. `.data` carries `posted_inline`, `posted_pr_level`, `deduped`, `submitted`, `event`,
`decision`, `review_url`, `blocked_by_unresolved`, `skipped_reason` (`"unchanged"` for a no-op skip, else
`""`) and `retry_pending` (rows not yet delivered; `0` on a full success). `.data.submitted = false` with
`skipped_reason = "unchanged"` and `status: "ok"` is a deliberate skip, not a failure; with `status: "partial"` it
means the review could not be confirmed (`.warnings` says what to do, and `retry_pending` may be `0` when the
review carried no rows). `.warnings` is a list of `{code, message}` objects — `retry_pending`, `retry_not_saved`,
`retry_not_requested`, `retry_truncated`, `retry_given_up`, `review_unconfirmed`, `review_rejected` — so the
envelope always passes the checker, even on a partial outcome. Every field is report-only here — none of them
gates a branch this skill takes independently of `.data.decision` (a blocking thread already forces
`decision` to `COMMENT`, see "Semantic shift" below) — so every field is read straight from
`$RESULT` with `jq` at the point it's used, always `printf '%s' "$RESULT" | jq ...` or `jq
... <<<"$RESULT"`, **never** `echo "$RESULT" | jq`, per
[`shared/docs/shell-echo-vs-printf.md`](../../shared/docs/shell-echo-vs-printf.md). Finding bodies
are never echoed to stdout, so a body containing shell metacharacters can never inject into
anything downstream.

**Semantic shift:** `.data.decision = APPROVE` now means "no Critical/High in this run's findings
**and** no open (unresolved, non-outdated) review threads on the PR" — not just the former. Any
unresolved, non-outdated thread force-downgrades `APPROVE` to `COMMENT`, regardless of its
severity (GitHub threads carry no severity field). This is deliberately severity-blind and
orthogonal to the `swe-workbench:reviewer` agent's own footer, which still means "no Critical/High
in this diff, this run" exactly as before — the two criteria can legitimately disagree.

`APPROVE_OVER_OPEN_THREADS` is the one sanctioned way to submit `APPROVE` with open threads still present — when it fires (decision reaches `APPROVE`, `n_blocking > 0`, not self-review), the posted review body gains an `_Approved with {N} unresolved review thread(s) still open — override: {reason}._` line and the stderr "APPROVE downgraded" notice is suppressed for that run. `.data.approve_over_open_threads`/`.data.override_reason` report whether `--approve-over-open-threads` was **passed**, not whether it took effect — both stay `true`/populated even when the override was a no-op (e.g. self-review, or no blocking threads existed to begin with), so neither field alone is proof anything was overridden. `.data.blocked_by_unresolved` also always stays the true, non-zero count regardless of whether the override fired, so it alone isn't proof either. To confirm the override actually **prevented** a downgrade, check both conditions together: `.data.blocked_by_unresolved > 0` (there were blocking threads) **and** `.data.decision == "APPROVE"` (the decision still reached APPROVE despite them) — only that combination is conclusive.

**Residual risk:** GitHub's `isOutdated` reflects diff-*position* staleness (the thread's anchored
hunk no longer maps cleanly to HEAD), not whether the underlying concern was ever addressed — an
unrelated edit elsewhere in the file can flip a still-valid, never-addressed thread to outdated,
silently exempting it from the gate with no explicit action (unlike `isResolved`). Treat an
outdated-but-unresolved thread as needing manual re-verification, not as settled.

This skill ends once the review is submitted and offers no follow-up step; addressing feedback is a separate, explicit `/swe-workbench:address-feedback <N>` run.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| A pre-validated finding goes out-of-diff at post time, or the POST 422s outright (stale `commit_id`) | a `422`-bearing response | Demoted into the review body (never dropped); retried once against a re-fetched HEAD (`headRefOid`); a second 422 demotes every inline row for one body-only POST |
| POST fails on network/5xx or a timeout | A non-HTTP failure, a 5xx, or `HTTP 408/425/429` | Never blind-retried; the reviews are read back by run marker — landed means done, absent means one retry of the identical payload, unreadable means unconfirmed |
| GitHub refuses the review outright (401/403/404 or another 4xx besides 408/425/429, including a 422 that survives the retry ladder) | `.warnings[].code = "review_rejected"`, `status: "partial"` | No read-back and no retry — nothing was posted. The rows wait in `$RETRY_STATE`; fix the permission, auth or target and rerun. |
| Self-review, or `comments[]` is empty (`N == 0`) | `CURRENT_USER == AUTHOR_LOGIN`, or no inline survivors after dedup + pre-validate | Self-review always submits `.data.event = COMMENT`. Empty: the review carries only the summary and any PR-level batch. |
| Decision unchanged and nothing new | `.data.skipped_reason = "unchanged"`, `.data.submitted = false`, `status: "ok"` | Zero mutations — nothing was posted on purpose. |
| All findings dedup-matched | `.data.posted_inline = 0` and `.data.posted_pr_level = 0` | Submit proceeds unless the decision is also unchanged (then it is skipped, above). |
| More PR-level findings than the body holds, and an overflow batch post fails | `[warn]` on stderr, `.data.retry_pending > 0`, `status: "partial"` | The review itself landed; only the failed rows are kept in the retry file for the next run. |
| Unresolved, non-outdated review thread(s) exist from a prior review | `.data.blocked_by_unresolved > 0` | `APPROVE` force-downgraded to `COMMENT`, severity-blind by design. Resolve the thread(s) — manually, or via `/swe-workbench:address-feedback`'s ADDRESSED/CLARIFIED/DEFERRED triage — to unblock a future `APPROVE`; or pass `APPROVE_OVER_OPEN_THREADS` to submit `APPROVE` anyway for a thread deliberately left open. |
| Every submit path exhausted with nothing confirmed | `status: "partial"`, `.data.submitted = false`, a `.warnings` entry, usually `.data.retry_pending > 0` | The script still exits 0 (never aborts the caller's flow); treat every count in `.data` as best-effort rather than a confirmed post. The unconfirmed rows wait in `$RETRY_STATE`; re-running the same review merges them. |
| The outgoing payload fails its pre-POST check (e.g. an oversized body) | exit 1, no envelope, `refusing to post an invalid review payload` on stderr | Nothing was posted. Shorten the offending finding text and rerun. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Re-deriving the fetch/dedup/pre-validate/submit mechanism inline instead of calling `swe-workbench-pr-review-submit` | The script is the single source of truth for posting mechanics — every caller invokes it the same way |
| Passing a byline that embeds the swe-workbench remark or `posted`/`deduped` counts | The script appends both once it knows the real counts and confirmed repo visibility — an embedded byline fails input-contract validation |
| Reading `.data.submitted = false` as a failure | Check `.data.skipped_reason` first: `"unchanged"` is a deliberate no-op, not a posting failure |
| Reading `.data.posted_inline`/etc. before checking `.data.submitted` (or `status`) | A `false` `.data.submitted` with `status: "partial"` means delivery could not be confirmed (the rows wait in the retry file); treat the counts as best-effort in that case |
| Using `echo "$RESULT" \| jq` instead of `printf '%s' "$RESULT" \| jq` or `jq ... <<<"$RESULT"` | `echo` on a JSON-bearing variable can corrupt it — see `shared/docs/shell-echo-vs-printf.md` |
