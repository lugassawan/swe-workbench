---
description: Drive a feature implementation end-to-end from a ticket or spec — branch, plan, build, verify, review, deliver
argument-hint: <ticket ref, GitHub issue URL, or feature description>
---

Feature request: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

Activate the `swe-workbench:workflow-development` skill in **Mode B (Implementation-Time Behavior)**. Execute all five phases in order:

**Phase 1 — Branch**
Isolate this work in a worktree when the scope warrants it (non-trivial changes, risk of destabilizing main). For tiny single-file changes, skip with a written rationale. `workflow-development` Phase 1 will detect the worktree provider automatically: `rimba add <task>` when rimba is available (PATH or common install locations), otherwise `superpowers:using-git-worktrees`.

**Phase 2 — Implement**
- **Architectural consult (conditional):** If the ticket implies a new service, a boundary or contract change, a technology choice, or any non-trivial design fork — invoke the `senior-engineer` subagent *before* plan-writing for a boundary/trade-off read. Fold its output into the plan.
- If no written plan exists, draft one via `superpowers:writing-plans`. Before finalizing the plan, activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so placeholders are substituted from this repo, not left as `[[detect:…]]`. Since `/implement` always modifies the codebase, Mode A always applies here.
- Execute via `superpowers:executing-plans` for sequential work, or `superpowers:subagent-driven-development` for parallelizable units.
- Apply `swe-workbench:principle-tdd` per implementation unit: red → green → refactor.
- **Mid-implementation forks:** If an architectural decision emerges that was not anticipated in the plan, pause and consult `senior-engineer` rather than guessing. Update the plan before continuing.

**Phase 3 — Verify**
Run `superpowers:verification-before-completion` before claiming any phase done. Do not advance to Phase 4 until this passes clean.

**Phase 4 — Review**
Dispatch both reviewers: `superpowers:code-reviewer` (plan-alignment) and the `reviewer` subagent (diff correctness/security/design). Do not advance to Phase 5 until review passes clean or all raised issues are resolved.

**Phase 5 — Deliver**
Use the PR template path recorded in Project Detection: pass it to `gh pr create --body-file <path>` and substitute the `Closes #` placeholder (with `Closes #123` or `Issue: N/A — <reason>`) before invoking. Only emit the heredoc body shown in Phase 5 of `templates/plan-workflow-section.md` if no template was found — do not re-invoke the template skill as a fallback. Then invoke `swe-workbench:workflow-commit-and-pr` to complete the delivery. After the PR is merged (by you or a reviewer), run `/swe-workbench:cleanup-merged <N>` to remove the worktree and local + remote branch.

Absolute rules:
- If the ticket lacks acceptance criteria, stop and ask the user — do not invent scope.
- Do not skip Phase 3 (verify) or Phase 4 (review) under any circumstances.
- Phase 2 is TDD per unit: write the failing test first, then the implementation, then refactor.
- Do not invent architectural answers — escalate any design fork to `senior-engineer`.
- Do not open the PR (Phase 5) until Phases 3 and 4 both pass clean.
