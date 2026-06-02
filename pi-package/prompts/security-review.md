---
description: Depth-first security audit of the current git diff — OWASP Top 10, secret leakage, insecure-by-default APIs, and language-specific foot-guns. Pass a PR number to audit a specific PR's diff.
argument-hint: "[PR number — optional; omit to audit local diff]"
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its summary to the delegation context. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `security-auditor` subagent with the resolved diff (PR diff via `gh pr diff <N>` if $ARGUMENTS is a PR number — stripping a leading `#` if present; otherwise the local-diff cascade: `git diff` → `git diff --staged` → `git diff origin/main...HEAD`). Ask for a prioritized findings report.

## Output

The `security-auditor` subagent produces a severity-organized findings report. Expect:

- **Critical** — data exfiltration, authentication bypass, direct secret exposure, remote code execution risk.
- **High** — exploitable injection (SQLi, XSS, SSRF, XXE), broken access control, insecure deserialization.
- **Medium** — missing input validation at trust boundaries, insecure defaults, weak cryptographic choices.
- **Low** — defence-in-depth gaps, minor information-disclosure risks, dependency CVEs with low exploitability.

Each finding uses: `Severity | File:Line | Issue | Why it matters | Suggested fix`. The report closes with a short summary section (total counts by severity, surface areas touched, recommended next action).
