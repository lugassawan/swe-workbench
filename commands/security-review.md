---
description: Audit the current git diff for security vulnerabilities — OWASP Top 10, secrets, insecure APIs, dependency CVEs
argument-hint: "[ticket ref or leave blank to audit current diff]"
---

Audit the pending changes on this branch for security vulnerabilities.

1. Gather the diff:
   - Run `git diff` for unstaged changes.
   - Run `git diff --staged` for staged changes.
   - If both are empty, run `git diff origin/main...HEAD` (or `origin/master...HEAD`).
2. Detect ticket references: check the current branch name (`git rev-parse --abbrev-ref HEAD`) and recent commit messages (`git log --oneline -5`) for ticket keys (`[A-Z]+-\d+`), `atlassian.net` URLs, Confluence wiki URLs, or GitHub issue/PR refs. If found, invoke `swe-workbench:ticket-context` with the ticket reference and prepend its summary to the auditor context — knowing the intended change helps identify which trust boundaries the diff crosses.
3. Invoke the `security-auditor` subagent with the diff and ask for a prioritized security report.
4. Organize findings by severity, highest first:
   - **Critical** — exploitable now, no preconditions (exposed live secret, unauthenticated RCE, SQLi in user-reachable endpoint).
   - **High** — exploitable with reasonable preconditions (SSRF, IDOR, missing auth on internal API, weak crypto for sensitive data).
   - **Medium** — defense-in-depth gaps (missing rate limit, verbose error messages, missing security headers).
   - **Low** — hygiene (outdated dep with no known exploit path, missing CSP `report-uri`).
5. Each finding uses: `Severity | File:Line | Issue | Why it matters | Suggested fix`.
6. Close with a short tally: number of Critical / High / Medium / Low findings, and one sentence per non-zero category summarizing the pattern.
