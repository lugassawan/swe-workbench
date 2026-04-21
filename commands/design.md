---
description: Consult the senior-engineer subagent for an architectural decision
argument-hint: <design question>
---

The user is asking: $ARGUMENTS

If $ARGUMENTS contains a ticket reference (Jira key like `PROJ-123`, an `atlassian.net` URL, a Confluence wiki URL, or a GitHub issue/PR URL or `#NNN`), invoke the `swe-workbench:ticket-context` skill first and prepend its structured summary so the subagent has the full design brief.

Delegate to the `senior-engineer` subagent. Its response must contain:

1. **Problem restatement** — confirm the real question and surface implicit constraints (scale, team size, change frequency, latency budget, compliance).
2. **Options** — 2–3 candidate approaches, each with sketch, strengths, weaknesses, and reversibility.
3. **Recommendation** — one option chosen, reasoned against Clean Architecture's dependency rule and DDD boundaries where relevant.
4. **Risks** — what could make this choice wrong, and which signals to watch.

If the question is under-specified, the subagent asks clarifying questions before recommending. Call out YAGNI explicitly when the design is premature.
