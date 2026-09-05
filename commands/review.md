---
description: Review the current git diff — auditor selected by --mode (general, security, a11y, deps, perf, tests, contributor-trust, ux) or auto-inferred from the diff when omitted. Pass a PR number to review a specific PR; use --check-followup <N> to re-check a PR after the owner has addressed feedback.
argument-hint: "[--mode <general|security|a11y|deps|perf|tests|contributor-trust|ux>] [PR number — optional] [--check-followup <PR number>]"
---

Review code with senior-engineer depth. Two dimensions — fully orthogonal:

- **Auditor axis (`--mode`):** which specialist reviews the diff (general / security / accessibility / dependency / performance / tests / contributor-trust). Auto-inferred from the diff when omitted.
- **Diff-source axis:** local working-tree diff vs. PR diff. Determined by the remaining arguments after `--mode` is stripped.

## Step 1 — Argument resolution

Parse `$ARGUMENTS` left-to-right:

0. If `--check-followup <N>` is present (where `N` is a PR number), strip it and enter **Followup mode** — see `## Followup mode` below. All other flags and argument parsing are skipped.

1. If a `--mode <value>` flag is present, extract it and normalize the alias:

   | `--mode` value (and aliases) | Normalized mode | Delegates to |
   |---|---|---|
   | `general` | `general` | `swe-workbench:reviewer` |
   | `security`, `sec` | `security` | `swe-workbench:security-auditor` |
   | `accessibility`, `a11y` | `accessibility` | `swe-workbench:accessibility-auditor` |
   | `dependency`, `deps` | `dependency` | `swe-workbench:dependency-auditor` |
   | `performance`, `perf` | `performance` | `swe-workbench:performance-tuner` |
   | `tests` *(no short alias — keyword is already short)* | `tests` | `swe-workbench:test-reviewer` |
   | `contributor-trust`, `trust` | `contributor-trust` | `swe-workbench:contributor-auditor` |
   | `ux` *(no short alias)* | `ux` | `swe-workbench:product-designer` |

   Strip `--mode <value>` from `$ARGUMENTS`. Store the normalized mode. If the value is unrecognized, print an error listing valid values and stop.

2. The remaining `$ARGUMENTS` (after stripping `--mode`) flow into diff-source detection:
   - Matches `[1-9][0-9]*` (stripping a leading `#` if present) → **PR mode** with that number.
   - Else, run `gh pr view --json number,headRefName 2>/dev/null`. If it succeeds (current branch has an open PR), print:
     > "Detected PR #N on this branch — review it? Reply `yes` to enter PR mode, or `local` to review the local diff instead."

     Wait for the user's reply. `yes` → **PR mode**. `local` (or anything else) → **local-diff mode**.
   - Else → **local-diff mode**.

## Step 2 — Mode resolution

**If `--mode` was provided:** use the normalized mode from Step 1. Print:
> `Mode: <normalized-mode> (explicit)`

**If `--mode` was omitted:** obtain the changed-file list from the **resolved diff source** (not the local working tree):
- PR mode: `gh pr diff <N> --name-only`
- Local-diff mode: `git diff --name-only` (unstaged → staged → `origin/main...HEAD` cascade)

Apply these inference rules **in precedence order** (first match wins; ties resolve to the earlier rule). For rules that inspect diff content (3, 4), read the full diff from the same source (`gh pr diff <N>` or the local-diff cascade):

1. **dependency** — ALL changed files are manifest or lockfiles: `package.json`, `package-lock.json`, `Cargo.toml`, `Cargo.lock`, `go.mod`, `go.sum`, `requirements*.txt`, `pyproject.toml`, `poetry.lock`, `uv.lock`, `yarn.lock`, `pnpm-lock.yaml`.
2. **security** — diff touches secret-handling, auth, or input-parsing surfaces: paths matching `**/auth*`, `**/security*`, `**/middleware*`, `**/sessions*`, `**/.env*`, `**/secrets*`, `**/parsers/**`, `**/serializers/**`.
3. **accessibility** — ALL changed files are frontend surfaces (`*.jsx`, `*.tsx`, `*.html`, `*.css`, `*.svelte`, `*.vue`) AND the diff content includes interactive markup (`<button`, `<input`, `<a `, `<form`, `<dialog`, `role=`, `aria-`).
4. **performance** — diff touches perf-sensitive hot-path globs (`**/cache/**`, `**/queries/**`, `**/db/**`, `**/index*`, `**/search*`) AND the diff is small (< 200 lines changed).
5. **general** — fallthrough when none of the above match.

> **Note:** `tests`, `contributor-trust`, and `ux` are intentionally absent from auto-inference — all must be requested explicitly. `tests` rationale: test files are also valid targets for general review, so auto-routing would suppress the full-spectrum `swe-workbench:reviewer` on test-only diffs. `contributor-trust` rationale: author signal and pattern-risk checks only make sense on PRs from external contributors; auto-firing on local diffs would add noise with no signal. `ux` rationale: UX-only diffs are rare and subjective; the caller must opt in deliberately to avoid noisy UX reports on backend-only changes.

Print exactly:
> `Inferred mode: <mode> — reason: <one-sentence justification>`

The user can override any inferred mode by re-invoking with an explicit `--mode`.

## Local-diff mode

1. Gather the diff:
   - Run `git diff` for unstaged changes.
   - Run `git diff --staged` for staged changes.
   - If both are empty, run `git diff origin/main...HEAD` (or `origin/master...HEAD`).
2. Detect ticket references: check `git rev-parse --abbrev-ref HEAD` and `git log --oneline -5` for ticket keys (`[A-Z]+-\d+`), `atlassian.net` URLs, Confluence wiki URLs, or GitHub issue/PR refs. If found, invoke `swe-workbench:ticket-context` and prepend its summary.
3. Invoke the **resolved auditor** (from Step 2) with the diff and ask for a prioritized report. Do not instruct the agent to emit a Decision footer — local-diff mode output is unchanged.
4. Organize findings by severity, highest first:
   - **Critical** — data loss, security breach, production outage risk.
   - **High** — correctness bugs, broken contracts, missing auth/validation.
   - **Medium** — design smells, SOLID violations, maintainability risks.
   - **Low** — naming, minor clarity.
5. Each finding uses: `Severity | File:Line | Issue | Why it matters | Suggested fix`.
6. Close with a short section summary: correctness bugs, security issues, design smells, test gaps.

Ground judgements in SOLID and Clean Architecture principles. Do not nitpick formatting — that is the linter's job.

**No posting prompt appears in this mode, ever** — there is no PR to post to. The post/skip `AskUserQuestion` confirmation (see `## Specialist post sub-flow` below) is exclusive to PR mode's postable specialist set; local-diff mode always just prints findings, unconditionally.

## PR mode

**When `--mode` is absent or `--mode general`:** invoke `swe-workbench:workflow-pr-review` via the `Skill` tool with `MODE=auto`, passing the resolved PR number. The skill self-detects first-pass vs. followup by checking whether this reviewer already has a review on the PR and whether it's still open — `--check-followup <N>` below remains available as an explicit override that always forces `MODE=followup`.

The skill owns: pre-flight (`gh auth`, `gh pr view`), ephemeral worktree under `/tmp/swe-workbench-pr-review/<N>`, ticket-context chain, reviewer invocation with footer instruction, decision-footer parsing, GraphQL thread fetch + dedup + REST inline-comment post, `gh pr review --approve|--comment` submission, non-blocking cleanup. See `skills/workflow-pr-review/SKILL.md` for the full 7-step contract and failure-mode handling.

**When `--mode` is set to a postable specialist value (security, accessibility, dependency, performance, tests, ux) with a PR number:** fetch the PR diff via `gh pr diff <N>` and run the specialist auditor against it in local-diff style — severity-organized findings, same format as local-diff mode above. This mode is **postable**: after printing findings, offer to post them through the same dedup/post/submit machinery `swe-workbench:workflow-pr-review` uses, rather than hand-constructing `gh api` calls that would bypass its dedup and thread-safety logic. See `## Specialist post sub-flow` below.

**When `--mode contributor-trust`:** run `swe-workbench:contributor-auditor` against the PR diff and print its findings (including the closing **Merge confidence** footer), then append: "Trust triage is advisory — not posted to the PR." **Stop** — `swe-workbench:contributor-auditor`'s contract is advisory-only and never posts; this mode is signal-only and skips the sub-flow below entirely.

If the PR number was obtained via auto-detect (user replied `yes` to the prompt in Step 1) rather than an explicit argument, the same branching applies: `--mode general` (or no `--mode`) delegates to `swe-workbench:workflow-pr-review`; `contributor-trust` is signal-only; every other mode is postable per the sub-flow below.

## Specialist post sub-flow

**The post/skip `AskUserQuestion` prompt below fires in exactly one case: a postable specialist mode (security, accessibility, dependency, performance, tests, ux) resolved in PR mode.** It never fires for `contributor-trust` (advisory-only, see above — stops before reaching this section) and never fires for local-diff mode (there is no PR to post to — see the explicit "no posting prompt" note in `## Local-diff mode` above). General mode has its own posting flow inside `swe-workbench:workflow-pr-review` and does not go through this sub-flow either.

1. **Preflight:** reuse `swe-workbench-preflight-pr` for `owner`/`repo`/`head_sha`/`base`/`author_login`. Derive the repo scope first: `SCOPE_SLUG=$(swe-workbench-repo-scope 2>/dev/null) || SCOPE_SLUG=""` — then pass `JSON="/tmp/swe-workbench-pr-review/${SCOPE_SLUG:+${SCOPE_SLUG}-}${PR}-review-${MODE}.json"` (mode-scoped and repo-scoped, distinct from `swe-workbench:workflow-pr-review`'s own first-pass/followup files, so a specialist run never collides with a concurrent general or followup review of the same PR — and same-numbered PRs in different repositories never collide with each other; empty slug falls back to the legacy un-scoped names) — plus `gh api /user -q .login` for `current_user`. Also allocate this sub-flow's own run-scoped scratch dir: `RUN_DIR=$(swe-workbench-new-run-dir "review-${MODE}" "$PR")` — `$RUN_DIR` is a mode-0700 directory under `/tmp/swe-workbench-run/`, slug-scoped by the same ladder, for ad-hoc bash artifacts, distinct from the mode-scoped state file above.
2. **Ephemeral worktree:** `eval "$(swe-workbench-pr-review-worktree acquire --mode "$MODE" --pr "$PR")"` — the same command `swe-workbench:workflow-pr-review` Step 2 uses, passed this sub-flow's own normalized `$MODE` (e.g. `security`). Sets `$WT` (absolute path), `$TASK`/`$BRANCH` (`review-<mode>-<N>`), `$PROVIDER`, `$CREATED` — the mode-scoped naming (so a specialist run's worktree/branch never collides with a general review's `pr-review-<N>` or another specialist mode's own run) is derived internally by that command, not by this sub-flow.
3. Run the specialist auditor against `git -C "$WT" diff "origin/$BASE"...HEAD`; print severity-organized findings (unchanged from the existing specialist output above).

   **On auditor error:** call `eval "$(swe-workbench-pr-review-worktree release --mode "$MODE" --pr "$PR" --intent failed)"` (preserves the worktree for inspection — this is an aborted-mid-scan state, the same terminal intent `swe-workbench:workflow-pr-review` Step 5 uses), reap `$JSON` via `swe-workbench-clean-state-files` and `$RUN_DIR` via `swe-workbench-reap-run-dir`, then stop — there are no findings to prompt on.
4. **Prompt:** call the `AskUserQuestion` tool — not a free-text "reply post/skip" prompt (matching the `AskUserQuestion` pattern `swe-workbench:workflow-pr-review-post`'s own Step 5 CTA already uses, for the same reason: a clickable button beats "type a keyword"):

   ```json
   {
     "questions": [{
       "question": "Post these findings to PR #<N> as inline comments + a review decision?",
       "header": "Post findings",
       "multiSelect": false,
       "options": [
         { "label": "Post", "description": "Submit as inline comments + a review decision via workflow-pr-review-post (dedup-safe)." },
         { "label": "Skip", "description": "Leave findings as printed above — nothing posted to the PR." }
       ]
     }]
   }
   ```

   Substitute the real PR number for `<N>`. On **Skip** (or any other answer), stop — no posting; reap this sub-flow's own `$JSON` via `swe-workbench-clean-state-files` and `$RUN_DIR` via `swe-workbench-reap-run-dir`, then tear down the worktree via `eval "$(swe-workbench-pr-review-worktree release --mode "$MODE" --pr "$PR" --intent declined)"` — this is a clean exit, not an aborted-mid-scan state, so unlike the auditor-error branch above (or `swe-workbench:workflow-pr-review` Step 5's abort case) the worktree is removed, not preserved for inspection.
5. **On `Post`:** normalize the auditor's documented finding rows into `FINDINGS[]` — `severity` and `body` (fold any extra columns, e.g. `swe-workbench:test-reviewer`'s `Category`, into `body`) from every row; `path`/`line` from `File:Line` when present. Set `anchor=inline` when a `File:Line` exists AND the line falls on a `+` line (not a context line) in `git -C "$WT" diff "origin/$BASE"...HEAD`; `anchor=pr-level` otherwise — `swe-workbench:dependency-auditor` rows have no `File:Line` and always anchor `pr-level`. Derive `DECISION`: at least one row with `severity ∈ {Critical, High}` → `COMMENT`; otherwise `APPROVE` (no footer to parse — these auditors don't emit one; this mirrors the general reviewer's own APPROVE-unless-Critical/High convention rather than flipping to `COMMENT` on any finding regardless of severity). Invoke `swe-workbench:workflow-pr-review-post` with:
   - `PR`, `OWNER`, `REPO`, `HEAD_SHA`, `BASE`, `CURRENT_USER`, `AUTHOR_LOGIN` — from Step 1.
   - `DECISION` — as derived above.
   - `BLOCKING_SCOPE` — intentionally omitted; specialist auditors don't classify in-diff vs out-of-diff, so it falls back to the core's `IN-DIFF` fail-safe default and the diff-scoping flip never fires for specialist-mode reviews (unlike `swe-workbench:workflow-pr-review` in either mode, which does set it from the reviewer agent's own classification).
   - `BYLINE` — `` _Reviewed by `<auditor>`_ `` (identity-only — substitute the specific agent from the mode table, e.g. `swe-workbench:security-auditor`; the core appends the swe-workbench remark itself, conditionally on public repos).
   - `CALLER_TAG` — the mode name (e.g. `security`).
   - `RUN_DIR` — this sub-flow's own Step 1 allocation, for the core's optional mid-workflow debug persist.
   - `FINDINGS[]` — as normalized above.

   Then reap `$JSON` via `swe-workbench-clean-state-files` and `$RUN_DIR` via `swe-workbench-reap-run-dir`, and tear down the worktree via `eval "$(swe-workbench-pr-review-worktree release --mode "$MODE" --pr "$PR" --intent completed)"`.

## Followup mode

**Trigger:** `--check-followup <N>` where `N` is a PR number (with or without leading `#`).

**Purpose:** the reviewer has already posted a full review; the owner pushed fixes; this re-checks for new findings, posts only truly-new inline comments, and submits APPROVE or COMMENT.

Invoke `swe-workbench:workflow-pr-review` via the `Skill` tool with `MODE=followup`, passing the resolved PR number.

The skill owns: pre-flight (`gh auth`, `gh pr view`, plus a followup-only open-PR gate), ephemeral worktree (`--task "pr-followup-$PR"` to avoid colliding with prior primary-review worktrees), ticket-context chain, `swe-workbench:reviewer` agent invocation, dedup against existing threads (Jaccard ≥ 0.4, ±5-line), posts only truly-new inline comments, and submits an APPROVE or COMMENT review event. See `skills/workflow-pr-review/SKILL.md` for the full 7-step contract and its mode-resolution table.
