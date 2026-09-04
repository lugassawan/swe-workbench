---
name: workflow-pr-review
description: Use when reviewing a remote GitHub PR — a first-pass peer review, or a followup re-check after the owner has addressed feedback. Fetches into an ephemeral worktree, runs the reviewer agent against the updated diff with a Review Decision footer instruction, deduplicates findings against existing review threads (±5-line fuzzy match + Jaccard ≥ 0.4 against any author), posts only truly-new deduped inline comments via gh-api, and submits the review decision with APPROVE or COMMENT.
orchestrator: true
---

# Workflow: PR Review (remote-PR orchestration shell)

**Announce at start:** "I'm using the workflow-pr-review skill to review PR #N." (first-pass mode) or "...to re-check PR #N." (followup mode).

## Mode resolution

This skill runs in one of two modes, chosen by the caller: **first-pass** (a fresh review) or **followup** (a re-check after the owner has addressed feedback). `commands/review.md` sets `MODE=auto` for a bare `/swe-workbench:review <N>` invocation and `MODE=followup` for `--check-followup <N>`. `MODE=auto` self-resolves to `first-pass` or `followup` at the top of Step 1 — see below — before mode-table interpolation happens, so everything downstream only ever sees a concrete `first-pass`/`followup` value.

Four values are derived from `$MODE` once, up front, and interpolated into every downstream bash block below — evaluated, not applied by hand:

| Var | `first-pass` | `followup` |
|---|---|---|
| `MODE_TAG` | `pr-review` | `pr-followup` |
| `STATE_SUFFIX` | *(empty)* | `-followup` |
| `CALLER_TAG` | `general` | `followup` |
| `BYLINE` | `_Reviewed by \`reviewer\`_` | `_Re-reviewed by \`reviewer\`_` |

The resolution itself happens at the top of Step 1 (the `case "$MODE"` block), which also echoes `Mode: $MODE` so mode selection is visible in the transcript — mirroring what `commands/review.md` already prints (`Mode: <normalized-mode> (explicit)` / `Inferred mode: <mode> — reason: ...`) for its own `--mode` selection.

## When to invoke

- The user passes a PR number to `/swe-workbench:review` (e.g. `/swe-workbench:review 123`) — first-pass mode.
- The user accepts the auto-detect prompt on `/swe-workbench:review` no-arg ("Detected PR #N — review it? Reply `yes`") — first-pass mode.
- The user runs `/swe-workbench:review --check-followup <N>` — followup mode.
- An agent or command needs to "review this remote PR end-to-end" — fetch + analyse + post + submit.
- Phrases (first-pass): "review PR 123", "do a peer review of #456", "fetch this PR and post deduped comments".
- Phrases (followup): "re-check PR 123", "check if my review comments were addressed", "follow up on review #456".

## When NOT to invoke

- Local-diff review (working tree / staged / branch diff) → use `commands/review.md` no-arg directly. The command stays the entrypoint for local-diff mode.
- `swe-workbench:workflow-development` Phase 4 → keeps using local-diff review (no remote PR exists yet during implementation).
- The user wants to post a single comment without running a full review → out of scope.
- The PR is closed/merged → out of scope for first-pass too, but followup mode additionally hard-gates on this (see Step 1).

## Composition

This skill orchestrates; analysis is delegated to:
- `swe-workbench:reviewer` subagent — produces `Severity | File:Line | Issue | Why | Fix` findings + a Review Decision footer (when instructed by this skill — see Step 4).
- `swe-workbench:ticket-context` skill — prepended to the reviewer prompt when the PR body or commit messages reference a ticket key, atlassian/Confluence URL, or `#NNN` GitHub ref.
- `swe-workbench:workflow-pr-review-post` skill — the shared posting core (Step 6): dedup, inline/PR-level posting, self-review gate + diff-scoping flip, submit, CTA, its own state reap.
- **Checkpoint:** write the workflow state file (see `shared/docs/workflow-state.md`) at each step boundary, carrying `$PR`/`$BASE`/`$HEAD_SHA`/`$DECISION` in `context`. Also populate `context.worktree_root` with `git rev-parse --show-toplevel`; omit it when working in the main checkout. This lets the resume hook emit a re-anchor nudge on compaction. Delete the state file after Step 7.

## 7-step flow

### Step 1 — Pre-flight

```bash
command -v swe-workbench-preflight-pr >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
if [ "$MODE" = auto ]; then
  gh auth status >/dev/null 2>&1 || { echo "gh not authenticated. Run 'gh auth login'." >&2; exit 1; }
  CURRENT_USER=$(gh api /user -q .login)
  MODE=$(gh pr view "$PR" --json state,reviews | jq -r --arg me "$CURRENT_USER" \
    'if .state == "OPEN" and ([.reviews[] | select(.author.login == $me)] | length) > 0
     then "followup" else "first-pass" end')
  echo "Auto-detected mode: $MODE"
fi
case "$MODE" in
  first-pass) MODE_TAG=pr-review;    STATE_SUFFIX="";          CALLER_TAG=general;  BYLINE='_Reviewed by `reviewer`_' ;;
  followup)   MODE_TAG=pr-followup;  STATE_SUFFIX="-followup"; CALLER_TAG=followup; BYLINE='_Re-reviewed by `reviewer`_' ;;
  *) echo "Unknown MODE: $MODE (expected auto, first-pass, or followup)" >&2; exit 1 ;;
esac
echo "Mode: $MODE"
# Repo scope (issue #713): origin-derived slug scopes the shared /tmp state
# namespace by repository; an unresolvable origin keeps legacy un-scoped names.
SCOPE_SLUG=$(swe-workbench-repo-scope 2>/dev/null) || SCOPE_SLUG=""
JSON="/tmp/swe-workbench-pr-review/${SCOPE_SLUG:+${SCOPE_SLUG}-}${PR}${STATE_SUFFIX}.json"
eval "$(swe-workbench-preflight-pr "$PR" "$JSON")"
if [ "$MODE" = followup ] && [ "$STATE" != "OPEN" ]; then
  swe-workbench-clean-state-files "$JSON"
  echo "PR #$PR is $STATE — follow-up review only applies to open PRs." >&2
  exit 1
fi
CURRENT_USER=$(gh api /user -q .login)
RUN_DIR=$(swe-workbench-new-run-dir "$MODE_TAG" "$PR")
```

`preflight-pr.sh` handles `gh auth status`, fetches the PR JSON to `$JSON`, and emits `BASE`, `HEAD_SHA`, `AUTHOR_LOGIN`, `OWNER`, `REPO`, `STATE` as shell assignments. `title`/`body` stay in `$JSON` — read them with `jq` when needed (Step 3 ticket-context). The JSON path is `${SCOPE_SLUG:+${SCOPE_SLUG}-}${PR}${STATE_SUFFIX}.json`: first-pass leaves `STATE_SUFFIX` empty (`<slug>-${PR}.json`); followup sets it to `-followup` (`<slug>-${PR}-followup.json`), so both can coexist for the same PR — and the owner-repo slug (issue #713, resolved once above via `swe-workbench-repo-scope`) keeps same-numbered PRs in different repositories from ever colliding; with no resolvable origin remote the empty slug falls back to the legacy un-scoped names. `new-run-dir.sh` allocates `$RUN_DIR` — a mode-0700 scratch directory under `/tmp/swe-workbench-run/`, itself slug-scoped by the same ladder, for this run's own ad-hoc bash artifacts (assembled JSON payloads, submit-response captures) that this flow's bash produces but never enumerates ahead of time. Distinct from `$JSON` above, which is a deliberate PR-keyed state file reaped by name in Step 7. The `if [ "$MODE" = followup ] …` guard is followup-only: a first-pass review proceeds regardless of PR state, while a followup re-check only makes sense while the PR is still open for further pushes. This gate runs immediately after the preflight fetch and before `$RUN_DIR` is allocated, so a rejected followup reaps `$JSON` inline via `swe-workbench-clean-state-files` rather than leaking it — `$RUN_DIR` never exists on this path, so there is nothing else to reap.

### Step 2 — Ephemeral worktree

`swe-workbench-pr-review-worktree` owns the acquire/release/naming contract for this ephemeral
worktree — the underlying rimba-vs-git provider choice, the collision-safe naming
(`pr-review-$PR` for first-pass, `pr-followup-$PR` for followup), and the stale/dirty self-heal
logic all live there, not in this skill's prose. `$MODE` is passed through as-is (`first-pass` or
`followup` — the exact vocabulary the mode table above already produces):

```bash
eval "$(swe-workbench-pr-review-worktree acquire --mode "$MODE" --pr "$PR")"
```

Sets `$WT` (absolute worktree path), `$TASK`/`$BRANCH` (the rimba task / worktree branch label),
`$PROVIDER` (`rimba` or `git`), and `$CREATED`.

### Step 3 — Ticket-context chain

Read `title` and `body` from the saved JSON. Match `[A-Z]+-\d+`, atlassian/Confluence URLs, or `#\d+`/PR refs in either field plus the last 5 commit messages (`git -C "$WT" log --oneline -5`). If matched, invoke `swe-workbench:ticket-context` and capture its summary as a prelude to the reviewer prompt.

### Step 4 — Invoke `swe-workbench:reviewer`

Pass the agent:
- Working-directory hint: absolute path of the worktree (`$WT`).
- Before diffing, refresh the remote base so already-merged commits are excluded (best-effort — a fetch failure is non-fatal): `git -C "$WT" fetch origin "$BASE" --quiet || true`
- Diff: `git -C "$WT" diff "origin/$BASE"...HEAD` (three-dot = merge-base; only commits unique to the PR branch).
- Repo-relative-path instruction (load-bearing): emit **repo-relative** paths (e.g. `src/foo.ts:42`, NOT `$WT/src/foo.ts:42`). The orchestrator uses these paths to position GitHub comments.
- Footer instruction (opt-in per `## Decision footer`): end with EXACTLY ONE of `**Review Decision: APPROVE**` or `**Review Decision: COMMENT**`. Never `REQUEST_CHANGES`.
- Blocking-scope instruction (opt-in per `## Blocking-scope verdict`): classify each Critical/High as in-diff (`+` lines) or out-of-diff; mark out-of-diff with `**Informational (out-of-diff):** `; emit `**Blocking Scope: NONE|OUT-OF-DIFF-ONLY|IN-DIFF**` before the footer. APPROVE/COMMENT rule unchanged.
- Ticket-context prelude (if Step 3 produced one).
- Symbol-navigation hint: `Grep`/`Glob` locates an anchor, then `bin/swe-workbench-lsp` (via `Bash`; the subagent's `LSP` grant, if any, is main-loop-only and unreachable here) expands from it — one attempt only; on no servers or error (exit 3), state `LSP unavailable — falling back to Grep` once and use Grep for the rest of the run. A language server may not be rooted at the ephemeral worktree `$WT` — pass `--root "$WT"`, which is exactly what the one-attempt fallback already handles if it still comes back empty.

This applies identically in both modes — followup re-checks re-run the same reviewer contract against the updated diff.

### Step 5 — Parse decision footer + blocking-scope verdict

Two abort paths share the same worktree-release contract below: the reviewer agent itself
erroring mid-scan (Step 4), and the footer-parse failure in this step. Both call
`swe-workbench-pr-review-worktree release --mode "$MODE" --pr "$PR" --intent failed` — which
preserves the worktree (never removes it), so inspection is still possible — instead of leaving
an implicit absence of any cleanup call. Do this immediately before printing the abort message
and exiting.

Scan ALL non-blank lines for the footer pattern:

```
^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$
```

Abort with "reviewer agent did not emit a valid Review Decision footer (APPROVE|COMMENT). Refusing to submit." if ANY of:
- Zero matches found.
- More than one matching line found.
- `REQUEST_CHANGES` appears anywhere in the agent output.

```bash
eval "$(swe-workbench-pr-review-worktree release --mode "$MODE" --pr "$PR" --intent failed)"
```

Also scan for `^\*\*Blocking Scope:\s+(NONE|OUT-OF-DIFF-ONLY|IN-DIFF)\*\*$`; parse into `$BLOCKING_SCOPE`. Zero or >1 matches → `BLOCKING_SCOPE=IN-DIFF` (fail-safe). Log warning; do **not** abort — footer is the only hard-required contract.

### Step 6 — Invoke the posting core

Parse Step 4's `swe-workbench:reviewer` output into `FINDINGS[]` rows (`severity`, `path`, `line`, `body`); anchor `inline` when the line is in-diff, `pr-level` otherwise (per the reviewer's own out-of-diff informational marker). Invoke `swe-workbench:workflow-pr-review-post` with:

- `PR`, `OWNER`, `REPO`, `HEAD_SHA`, `BASE`, `CURRENT_USER`, `AUTHOR_LOGIN` — from Step 1.
- `DECISION`, `BLOCKING_SCOPE` — parsed in Step 5.
- `BYLINE` — `$BYLINE` from the mode table above (`` _Reviewed by `swe-workbench:reviewer`_ `` for first-pass, `` _Re-reviewed by `swe-workbench:reviewer`_ `` for followup; identity-only — the core appends the swe-workbench remark itself, conditionally on public repos; see `skills/workflow-pr-review-post/SKILL.md` § Post).
- `CALLER_TAG` — `$CALLER_TAG` from the mode table above (`general` / `followup`; scopes the core's own threads-cache filename so it never collides with a concurrent run of the other mode or a specialist run on the same PR).
- `RUN_DIR` — this skill's own Step 1 allocation, for the core's optional mid-workflow debug persist (see `skills/workflow-pr-review-post/SKILL.md` § Post).
- `FINDINGS[]` — as parsed above.

The core owns thread fetch + dedup, inline/PR-level posting, the self-review gate + diff-scoping flip, submit, the address-feedback CTA, and its own state reap. See `skills/workflow-pr-review-post/SKILL.md` for the full contract, dedup algorithm, and failure modes.

### Step 7 — Cleanup

Foreground state-file reap for this skill's own preflight state (the core reaps its own separately) — runs immediately after Step 6 returns; failures surface (no `2>/dev/null` or `|| true`):

```bash
swe-workbench-clean-state-files "/tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json"
[ -e "/tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json" ] \
  && echo "⚠ state file NOT reaped: /tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json" >&2 \
  || echo "✓ state file reaped: /tmp/swe-workbench-pr-review/${PR}${STATE_SUFFIX}.json"
swe-workbench-reap-run-dir "$RUN_DIR"
[ -e "$RUN_DIR" ] \
  && echo "⚠ run dir NOT reaped: $RUN_DIR" >&2 \
  || echo "✓ run dir reaped: $RUN_DIR"
```

Worktree teardown now runs foregrounded, not backgrounded: `release`'s own output must be read
by the caller (`eval "$(...)"` cannot be backgrounded), and the acquired worktrees use
`--skip-deps --skip-hooks`, so removal is a directory + branch delete, not an `npm` dependency
tree — the original "slow" calibration was against a full dependency install that no longer
happens here:

```bash
eval "$(swe-workbench-pr-review-worktree release --mode "$MODE" --pr "$PR" --intent completed)"
```

Delete the workflow-state checkpoint file (see `shared/docs/workflow-state.md`) now that the flow has reached its terminal step.

## Footer parsing contract

- Regex: `^\*\*Review Decision:\s+(APPROVE|COMMENT)\*\*$`
- Source: scan ALL non-blank lines of agent output.
- Abort cases (do NOT submit, preserve worktree):
  - Zero matches.
  - More than one matching line.
  - `REQUEST_CHANGES` appears anywhere in the agent output.

Dedup algorithm, diff-scoping flip contract, and posting failure modes now live entirely in `skills/workflow-pr-review-post/SKILL.md` — this skill hands off decision + findings and does not duplicate that mechanism.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| `gh auth status` fails | Non-zero exit | Abort. Print fix hint. |
| PR not open / 404 | `gh pr view` fails | Abort. Print PR URL if known. |
| PR not open (followup mode only) | `$STATE != OPEN` after Step 1 preflight | Abort with "follow-up review only applies to open PRs." First-pass mode has no such gate. |
| `git fetch pull/N/head` fails | Non-zero exit | Abort. Do not create worktree. |
| Reviewer aborts mid-scan | Agent error | Skip submit. Call `release --intent failed` (preserves the worktree for inspection). |
| Decision footer missing or malformed | Regex no-match | Abort with explicit message. Call `release --intent failed` (worktree preserved). |

See `skills/workflow-pr-review-post/SKILL.md` § Failure modes for posting/dedup/submit failures (422s, stale SHA, pagination).

## Common mistakes

| Mistake | Fix |
|---|---|
| Invoke this skill without setting `$MODE` first | Every state-file path, worktree task name, byline, and caller tag is derived from `$MODE` via the mode-resolution table — an unset `$MODE` breaks every downstream interpolation. Callers must set `MODE=auto`, `MODE=first-pass`, or `MODE=followup` before Step 1. |
| Use `superpowers:using-git-worktrees` for the PR worktree | That skill is consent-gated and durable-feature-oriented. Use `swe-workbench-pr-review-worktree acquire --mode "$MODE" --pr "$PR"` instead — it owns the rimba-vs-git provider choice and the collision-safe naming. |
| Forget repo-relative-path instruction | GitHub comment positioning requires repo-relative paths. The agent will emit `$WT/...` paths otherwise — comments won't anchor. |
| Skip the footer instruction | Without it, the agent does NOT emit the footer (per its `## Decision footer (when instructed)` block). Step 5 will then abort. |
| Assume worktree teardown still backgrounds `(... ) &` | `release` runs foregrounded — its `eval "$(...)"` output must be read directly, and removal is fast (`--skip-deps --skip-hooks` worktrees have no dependency tree to clean up). |
| Reuse the core's own dedup/CTA/flip logic inline instead of invoking it | Duplicating that mechanism here is exactly the drift this skill was folded to remove — always delegate Step 6 to `swe-workbench:workflow-pr-review-post`. |
