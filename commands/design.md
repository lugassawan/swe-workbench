---
description: Consult the senior-engineer subagent for an architectural decision
argument-hint: <design question>
---

The user is asking: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary so the subagent has the full design brief. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `senior-engineer` subagent. Its response must contain:

1. **Problem restatement** — confirm the real question and surface implicit constraints (scale, team size, change frequency, latency budget, compliance).
2. **Options** — 2–3 candidate approaches, each with sketch, strengths, weaknesses, and reversibility.
3. **Recommendation** — one option chosen, reasoned against Clean Architecture's dependency rule and DDD boundaries where relevant.
4. **Risks** — what could make this choice wrong, and which signals to watch.

If the question is under-specified, the subagent asks clarifying questions before recommending. Call out YAGNI explicitly when the design is premature.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `<detected …>`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
