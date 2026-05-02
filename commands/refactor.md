---
description: Invoke the refactorer subagent for a behavior-preserving refactor
argument-hint: <file, function, or module>
---

Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first — a refactor motivated by a ticket needs the ticket's scope and constraints in the delegation context. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `refactorer` subagent. Its output must include:

1. **Diagnosis** — which smell is present (Long Method, Feature Envy, Primitive Obsession, Shotgun Surgery, Divergent Change, etc.) and why it hurts.
2. **Target state** — the shape of the code after refactoring, referenced to Fowler's catalog.
3. **Step plan** — ordered steps, each behavior-preserving and independently testable, each named from the catalog (Extract Function, Move Function, Replace Conditional with Polymorphism, Introduce Parameter Object…).
4. **Verification** — which tests protect each step; write characterization tests first if coverage is missing.

Absolute rule: no feature changes during refactoring.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `<detected …>`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
