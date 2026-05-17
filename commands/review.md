---
description: Review the current git diff — auditor selected by --mode (general, security, a11y, deps, perf, tests) or auto-inferred from the diff when omitted. Pass a PR number to review a specific PR; use --check-followup <N> to re-check a PR after the owner has addressed feedback.
argument-hint: "[--mode <general|security|a11y|deps|perf|tests>] [PR number — optional] [--check-followup <PR number>]"
---

Review code with senior-engineer depth. Two dimensions — fully orthogonal:

- **Auditor axis (`--mode`):** which specialist reviews the diff (general / security / accessibility / dependency / performance / tests). Auto-inferred from the diff when omitted.
- **Diff-source axis:** local working-tree diff vs. PR diff. Determined by the remaining arguments after `--mode` is stripped.

## Step 1 — Argument resolution

Parse `$ARGUMENTS` left-to-right:

0. If `--check-followup <N>` is present (where `N` is a PR number), strip it and enter **Followup mode** — see `## Followup mode` below. All other flags and argument parsing are skipped.

1. If a `--mode <value>` flag is present, extract it and normalize the alias:

   | `--mode` value (and aliases) | Normalized mode | Delegates to |
   |---|---|---|
   | `general` | `general` | `reviewer` |
   | `security`, `sec` | `security` | `security-auditor` |
   | `accessibility`, `a11y` | `accessibility` | `accessibility-auditor` |
   | `dependency`, `deps` | `dependency` | `dependency-auditor` |
   | `performance`, `perf` | `performance` | `performance-tuner` |
   | `tests` *(no short alias — keyword is already short)* | `tests` | `test-reviewer` |

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

> **Note:** `tests` is intentionally absent from auto-inference — it must be requested explicitly with `--mode tests`. Rationale: test files are also valid targets for general review, so auto-routing would suppress the full-spectrum `reviewer` on test-only diffs.

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

## PR mode

**When `--mode` is absent or `--mode general`:** invoke `swe-workbench:workflow-pr-review` via the `Skill` tool, passing the resolved PR number.

The skill owns: pre-flight (`gh auth`, `gh pr view`), ephemeral worktree under `/tmp/swe-workbench-pr-review/<N>`, ticket-context chain, reviewer invocation with footer instruction, decision-footer parsing, GraphQL thread fetch + dedup + REST inline-comment post, `gh pr review --approve|--comment` submission, non-blocking cleanup. See `skills/workflow-pr-review/SKILL.md` for the full 7-step contract and failure-mode handling.

**When `--mode` is set to a non-general value (security, accessibility, dependency, performance, tests) with a PR number:** fetch the PR diff via `gh pr diff <N>` and run the specialist auditor against it in local-diff style. **Inline-comment posting and APPROVE/COMMENT submission are skipped** — output is severity-organized findings only (same format as local-diff mode above). This avoids re-architecting `workflow-pr-review` to accept an auditor parameter; the full PR-review flow is reserved for the general reviewer.

If the PR number was obtained via auto-detect (user replied `yes` to the prompt in Step 1) rather than an explicit argument, the same branching applies: `--mode general` (or no `--mode`) delegates to `swe-workbench:workflow-pr-review`; non-general modes fetch `gh pr diff <N>` and run the specialist in local-diff style.

## Followup mode

**Trigger:** `--check-followup <N>` where `N` is a PR number (with or without leading `#`).

**Purpose:** the reviewer has already posted a full review; the owner pushed fixes; this re-checks for new findings, posts only truly-new inline comments, and submits APPROVE or COMMENT.

Invoke `swe-workbench:workflow-pr-review-followup` via the `Skill` tool, passing the resolved PR number.

The skill owns: pre-flight (`gh auth`, `gh pr view`), ephemeral worktree (`--task "pr-followup-$PR"` to avoid colliding with prior primary-review worktrees), ticket-context chain, `reviewer` agent invocation, dedup against existing threads (Jaccard ≥ 0.4, ±5-line), posts only truly-new inline comments, and submits an APPROVE or COMMENT review event. See `skills/workflow-pr-review-followup/SKILL.md` for the full 7-step contract.
