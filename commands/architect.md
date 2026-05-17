---
description: Author an ADR, RFC, or cross-service contract via the architect subagent
argument-hint: <decision question>
---

Decision: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `architect` subagent. Its output must include:

1. **Decision** — one paragraph stating what was chosen and why.
2. **Context & forcing function** — why this decision is needed now.
3. **Options considered** — table or bullets; all four sub-fields required for each option: strengths, weaknesses, operational cost, reversibility classification (one-way / two-way door).
4. **Consequences** — positive and negative; what becomes easier and what becomes harder or more expensive.
5. **Open questions** — what remains undecided and why it is safe to defer.
6. **References** — RFC numbers, prior ADRs, principle skills consulted, external standards cited.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
