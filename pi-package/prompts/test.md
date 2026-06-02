---
description: Invoke the test-writer subagent to add focused, behavioural tests in the target language's idiom
argument-hint: <file, function, or module>
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `test-writer` subagent. Its output must include:

1. **Behaviour inventory** — numbered list of all behaviours identified.
2. **Test file location and naming** — where the new tests live.
3. **Tests written** — count and names.
4. **Run result** — command used and pass / fail summary.
5. **Untested behaviours and why** — e.g., "covered by integration test", "trivial getter".

Absolute rule: no mocks for internal collaborators. If the code under test is hard to test as written, the agent must say so and recommend `/refactor` rather than mock around the design.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Since `/test` always adds test files to the codebase, Mode A always applies here.
