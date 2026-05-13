---
description: Invoke the migrator subagent to plan and execute a multi-deployment migration via expand → backfill → dual-write → switch → contract
argument-hint: <migration description>
---

Migration: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `migrator` subagent. Its output must include:

1. **Class** — DB schema, framework upgrade, runtime, API/contract, or event-schema. Determines the dominant hazard.
2. **Shapes** — current (A) and target (B) stated precisely, plus the call-site map (readers and writers enumerated).
3. **Strategy** — chosen approach (online vs. offline, phased vs. big-bang) with rationale; deferred to `senior-engineer` if ambiguous.
4. **Phase plan** — five phases (Expand → Backfill → Dual-write → Switch → Contract), each with what-happens / reversible-by / gate-to-advance slots filled in.
5. **Risks** — lock duration, backfill cost on a representative replica, sunset window vs. client release cycle.

Absolute rule: phases ship independently — never bundle two phases in one deployment.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
