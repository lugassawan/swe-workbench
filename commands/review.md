---
description: Review the current git diff with senior-engineer depth — correctness, security, design, and test gaps
---

Review the pending changes on this branch.

1. Gather the diff:
   - Run `git diff` for unstaged changes.
   - Run `git diff --staged` for staged changes.
   - If both are empty, run `git diff origin/main...HEAD` (or `origin/master...HEAD`).
2. Detect ticket references: check the current branch name (`git rev-parse --abbrev-ref HEAD`) and recent commit messages (`git log --oneline -5`) for ticket keys (`[A-Z]+-\d+`), `atlassian.net` URLs, Confluence wiki URLs, or GitHub issue/PR refs. If found, invoke `swe-workbench:ticket-context` with the ticket reference and prepend its summary to the reviewer context — the diff's intent is easier to evaluate against the full spec.
3. Invoke the `reviewer` subagent with the diff and ask for a prioritized report.
4. Organize findings by severity, highest first:
   - **Critical** — data loss, security breach, production outage risk.
   - **High** — correctness bugs, broken contracts, missing auth/validation.
   - **Medium** — design smells, SOLID violations, maintainability risks.
   - **Low** — naming, minor clarity.
5. Each finding uses: `Severity | File:Line | Issue | Why it matters | Suggested fix`.
6. Close with a short section summary: correctness bugs, security issues, design smells, test gaps.

Ground judgements in SOLID and Clean Architecture principles. Do not nitpick formatting — that is the linter's job.
