---
description: Drive a feature implementation end-to-end from a ticket or spec — branch, plan, build, verify, review, deliver
argument-hint: <ticket ref, GitHub issue URL, or feature description> [--grill | --standard]
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
Feature request: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.


Use pi-native execution for the lifecycle below: load packaged SWE Workbench skills when useful, use pi file/edit/bash tools for implementation, and avoid Claude-only skill names or tools.

Activate the `swe-workbench:workflow-development` skill in **Mode B (Implementation-Time Behavior)**. Execute all five phases in order:

**Phase 1 — Branch**
Isolate this work in a worktree when the scope warrants it (non-trivial changes, risk of destabilizing main). For tiny single-file changes, skip with a written rationale. Use `rimba add <task>` when rimba is available (PATH or common install locations), otherwise create the worktree manually with `git worktree add` or continue on the current branch for small safe changes.

**Phase 2 — Implement**
- **Architectural consult (conditional):** If the ticket implies a new service, a boundary or contract change, a technology choice, or any non-trivial design fork — load the packaged `agent-senior-engineer` skill before plan-writing for a boundary/trade-off read. Fold its output into the plan.
- If no written plan exists, draft an explicit step-by-step plan in the conversation or in the requested plan file. Before finalizing the plan, activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so placeholders are substituted from this repo, not left as `[[detect:…]]`. Since `/implement` always modifies the codebase, Mode A always applies here.
- Execute the plan step-by-step via pi tools for sequential work, split independent units into separate focused passes when parallelizable, or load `swe-workbench:workflow-delegated-implementation` when scope/complexity warrants grouping changes into focused `code-impl` dispatches to keep the orchestrator context lean.
- Apply `swe-workbench:principle-tdd` per implementation unit: red → green → refactor.
- **Mid-implementation forks:** If an architectural decision emerges that was not anticipated in the plan, pause and load `agent-senior-engineer` rather than guessing. Update the plan before continuing.

**Phase 3 — Verify**
Run the concrete verification commands defined in the plan or discovered from the project (imports/build/format/lint/tests as applicable) before claiming any phase done. Do not advance to Phase 4 until verification passes clean.

**Phase 4 — Review**
Review both plan alignment and diff quality: compare the implementation against the plan, then load the packaged `agent-reviewer` skill for diff correctness/security/design review. Do not advance to Phase 5 until review passes clean or all raised issues are resolved.

**Phase 5 — Deliver**
Use the PR template path recorded in Project Detection: pass it to `gh pr create --body-file <path>` and substitute the `Closes #` placeholder (with `Closes #123` or `Issue: N/A — <reason>`) before invoking. Only emit the heredoc body shown in Phase 5 of `templates/plan-workflow-section.md` if no template was found — do not re-invoke the template skill as a fallback. Then invoke `swe-workbench:workflow-commit-and-pr` to complete the delivery. After the PR is merged (by you or a reviewer), run `/swe-workbench:cleanup-merged <N>` to remove the worktree and local + remote branch.

Absolute rules:
- If the ticket lacks acceptance criteria, stop and ask the user — do not invent scope.
- Do not skip Phase 3 (verify) or Phase 4 (review) under any circumstances.
- Phase 2 is TDD per unit: write the failing test first, then the implementation, then refactor.
- Do not invent architectural answers — escalate any design fork to `senior-engineer`.
- Do not open the PR (Phase 5) until Phases 3 and 4 both pass clean.
