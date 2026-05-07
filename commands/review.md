---
description: Review the current git diff with senior-engineer depth — correctness, security, design, and test gaps. Pass a PR number (or accept the auto-detect prompt) to delegate PR-mode to the workflow-pr-review skill.
argument-hint: "[PR number — optional; omit to review local diff]"
---

Review code with senior-engineer depth. Two modes:
- **Local-diff mode** (default, no arg): review the working/staged/branch diff. (Used by `workflow-development` Phase 4.)
- **PR mode** (arg = PR number, or auto-detected from current branch with confirmation): delegate to `swe-workbench:workflow-pr-review` — fetch into ephemeral worktree, run reviewer, post deduped inline comments, submit APPROVE/COMMENT.

## Step 1 — Argument resolution + mode select

1. If `$ARGUMENTS` is a positive integer (`[0-9]+`) → **PR mode** with that number.
2. Else, run `gh pr view --json number,headRefName 2>/dev/null`. If it succeeds (current branch has an open PR), print:
   > "Detected PR #N on this branch — review it? Reply `yes` to enter PR mode, or `local` to review the local diff instead."

   Wait for the user's reply.
   - `yes` → **PR mode** with the auto-detected number.
   - `local` (or anything else) → **local-diff mode**.
3. Else → **local-diff mode**.

## Local-diff mode

1. Gather the diff:
   - Run `git diff` for unstaged changes.
   - Run `git diff --staged` for staged changes.
   - If both are empty, run `git diff origin/main...HEAD` (or `origin/master...HEAD`).
2. Detect ticket references: check `git rev-parse --abbrev-ref HEAD` and `git log --oneline -5` for ticket keys (`[A-Z]+-\d+`), `atlassian.net` URLs, Confluence wiki URLs, or GitHub issue/PR refs. If found, invoke `swe-workbench:ticket-context` and prepend its summary.
3. Invoke the `reviewer` subagent with the diff and ask for a prioritized report. **Do not** instruct the agent to emit a Decision footer — local-diff mode output is unchanged.
4. Organize findings by severity, highest first:
   - **Critical** — data loss, security breach, production outage risk.
   - **High** — correctness bugs, broken contracts, missing auth/validation.
   - **Medium** — design smells, SOLID violations, maintainability risks.
   - **Low** — naming, minor clarity.
5. Each finding uses: `Severity | File:Line | Issue | Why it matters | Suggested fix`.
6. Close with a short section summary: correctness bugs, security issues, design smells, test gaps.

Ground judgements in SOLID and Clean Architecture principles. Do not nitpick formatting — that is the linter's job.

## PR mode

Invoke `swe-workbench:workflow-pr-review` via the `Skill` tool, passing the resolved PR number.

The skill owns: pre-flight (`gh auth`, `gh pr view`), ephemeral worktree under `/tmp/swe-workbench-pr-review/<N>`, ticket-context chain, reviewer invocation with footer instruction, decision-footer parsing, GraphQL thread fetch + dedup + REST inline-comment post, `gh pr review --approve|--comment` submission, non-blocking cleanup. See `skills/workflow-pr-review/SKILL.md` for the full 7-step contract and failure-mode handling.
