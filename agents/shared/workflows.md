# Workflow catalog

All `swe-workbench` workflow and integration skills available in this plugin. Use the `Skill` tool to invoke any of these.

- `swe-workbench:workflow-audit-emit-issues` — Post-audit filing: groups codebase audit findings by subsystem (path prefix), discovers issue templates and labels, renders a batch preview, and files one GitHub issue per subsystem on `confirm`. Counterpart to `workflow-codebase-audit` (read-only); filing mirrors `workflow-bug-triage` Phase 4.
- `swe-workbench:workflow-bug-triage` — Investigate-and-file-issue counterpart to /debug. Iron Law (no fix without root cause), 4-phase loop, files structured issue with code-path table and impact assessment.
- `swe-workbench:workflow-cleanup-merged` — Post-merge cleanup: fast-forward main (which auto-cleans via rimba post-merge hook when active), then verify; falls back to `rimba remove` or `git worktree` shell path; deletes local + remote branch.
- `swe-workbench:workflow-codebase-audit` — Cold-start, time-boxed, multi-axis audit sweep with ranked findings, reasoning chains, and counter-evidence calibration.
- `swe-workbench:workflow-codebase-knowledge` — Understanding-oriented codebase presentation: architecture overview, module map, public API surfaces, and patterns — read-only, no defects, no new docs.
- `swe-workbench:workflow-commit-and-pr` — Pre-merge half: enforces [type] commit format, branch-naming, [no ci] for docs, draft/ready prompt, PR template detection, and post-create /review CTA.
- `swe-workbench:workflow-development` — Full development lifecycle: Branch → Implement → Verify → Review → Deliver. Phase 1 uses `rimba add` when rimba is available; falls back to `superpowers:using-git-worktrees`.
- `swe-workbench:workflow-delegated-implementation` — Phase-2 delegation strategy: conditional scope/complexity gate, file-change grouping (Infra/Core/Tests/Wiring axes), dispatch to the `code-impl` sub-agent, summary-only result consumption, sequential-default with opt-in worktree-isolated parallelism.
- `swe-workbench:workflow-extend` — Mid-PR sub-idea capture and implementation onto the existing branch. Skips Phase 1 (Branch), preserves Verify → Review → Deliver, updates the existing PR via workflow-commit-and-pr.
- `swe-workbench:workflow-grill` — Grill-me interrogation MODE for a scoped command's clarify step: walks the decision tree one question at a time with recommended answers, self-answers from the codebase, exits on shared understanding or "proceed", hands a Resolved-decisions block back to the command's artifact step. Activated by /capture /design /implement /architect /extend /debug. Not a from-scratch design flow; produces no design doc.
- `swe-workbench:workflow-address-feedback` — PR-owner feedback loop: fetch open review threads, per-thread ADDRESSED/CLARIFIED/DEFERRED triage, Edit-tool fixes, workflow-commit-and-pr commit, REST reply posting, and GraphQL resolveReviewThread. Invoked by `/address-feedback`.
- `swe-workbench:workflow-pr-review` — Remote-PR review orchestration: ephemeral worktree + reviewer agent + GraphQL thread dedup + REST inline-comment post + APPROVE/COMMENT submit. Invoked by `/review` PR mode.
- `swe-workbench:workflow-pr-review-followup` — Reviewer follow-up re-check: re-runs reviewer agent against the updated diff, deduplicates against existing threads (Jaccard ±5-line), posts only truly-new inline comments, and submits APPROVE/COMMENT. Invoked by `/review --check-followup <N>`.
- `swe-workbench:workflow-worktree-session` — Start, switch, or end a worktree-bound session via `EnterWorktree` / `ExitWorktree`. No claude restart.
- `swe-workbench:ticket-context` — Fetch structured context from Jira, Confluence, and GitHub issues/PRs before starting work.
