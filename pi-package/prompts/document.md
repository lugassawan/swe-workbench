---
description: Generate or update documentation (README, ADR, ARCHITECTURE, inline comments) via the tech-writer subagent
argument-hint: <artifact, file, or topic>
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

Delegate to the `tech-writer` subagent. Its output must include:

1. **Artifact type** — which category (README section, ADR, ARCHITECTURE/OVERVIEW, inline comment).
2. **Target path** — the exact file path the artifact will live at.
3. **Style notes detected** — heading case, voice, list style, em-dash usage, and any other conventions observed in existing top-level docs.
4. **Draft or diff** — the content to be written.
5. **Citations** — commit hash or file:line for every factual claim in committed artifacts; conversation excerpt is acceptable only in drafts.

Absolute rule: never invent behavior. If the diff doesn't show it, don't document it.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
