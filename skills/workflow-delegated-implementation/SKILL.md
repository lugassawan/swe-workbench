---
name: workflow-delegated-implementation
description: Phase-2 delegation protocol for workflow-development — conditional scope/complexity gate, file-change grouping by commit-taxonomy axis (Infrastructure/Core logic/Tests/Wiring), dispatch to code-impl with a structured brief (goal, file_set, verify_cmd), summary-only result consumption (re-read prevention), sequential-default with opt-in worktree-isolated parallelism. Distinct from superpowers:subagent-driven-development, which orchestrates tasks in parallel by default; the delegation protocol gates on scope, groups by commit-axis cohesion, and enforces a diff-free return contract.
orchestrator: true
---

# Workflow: Delegated Implementation

Phase-2 delegation strategy. When scope or complexity warrants it, the orchestrator groups related file changes, dispatches each cohesive group to a focused `code-impl` sub-agent, and consumes a concise verification summary instead of re-reading changed files. This keeps the orchestrator context lean and enables safe sequential (or opt-in parallel) execution.

**Announce at start:** "I'm using workflow-delegated-implementation to delegate [N] change groups to code-impl."

## When to invoke

Delegate when **any** of the following is true:

| Condition | Threshold | Rationale |
|---|---|---|
| File count | > 5 distinct files | Reading every diff fills orchestrator context |
| Module count | > 2 distinct modules/packages | Cross-module reasoning benefits from focused agents |
| Dependency depth | Changes span ≥ 2 dependency layers | Isolated agents reduce reasoning surface |
| Complexity | Non-trivial logic in ≥ 2 separate concerns | Each concern deserves focused attention |
| Explicit request | Orchestrator decides delegation is cleaner | Orchestrator judgment overrides thresholds |

Not gated by task type — delegation applies equally to features, fixes, and refactors.

## When NOT to invoke

Implement solo (via `superpowers:executing-plans`) when:

- The change touches a single file or a single module.
- The briefing overhead would exceed the implementation time (e.g., a one-line fix).
- All changes are tightly coupled and cannot be coherently grouped.

## Grouping changes

Reuse the commit-taxonomy axes from `workflow-development` to define cohesive groups. A group is cohesive when its files share the **same module boundary AND change together** (Connascence of Execution).

| Axis | Contains | Group when… |
|---|---|---|
| Infrastructure | Config, deps, build files | All config touching the same subsystem |
| Core logic | Main feature/fix implementation | Same module or bounded context |
| Tests | Test files and test utilities | Tests for the same implementation group |
| Wiring | Integration, routing, CLI registration | Entry-point wiring for the same feature slice |

**Group shape** (conceptual fields — the [Dispatch contract](#dispatch-contract) section below is the authoritative brief format):

```
ticket_slice: <one-line description of this group's goal>  → maps to Goal:
file_set: [explicit, disjoint list of relative file paths] → maps to File set:
verify_cmd: <command to run after implementation>          → maps to Verify command:
expected: <what "passing" looks like>                      → maps to the expected: line in your prose
```

**Worked example — adding a new workflow skill:**

| Group | file_set | verify_cmd |
|---|---|---|
| Core logic | `skills/my-skill/SKILL.md`, `skills/my-skill/triggers.txt` | `bash scripts/validate.sh` |
| Tests | `tests/test_my_skill.py` | `pytest tests/test_my_skill.py -v` |
| Wiring | `agents/shared/workflows.md`, `docs/catalog.md`, `README.md` | `bash scripts/validate.sh && pytest tests/ -q` |

Each group's `file_set` is disjoint — no file appears in two groups.

## Dispatch contract

Send each group to `code-impl` with this brief structure:

```
Goal: <ticket_slice>

Acceptance slice:
- <criterion 1>
- <criterion 2>

File set (edit only these files):
- <relative/path/to/file1>
- <relative/path/to/file2>

Work from: <absolute path of worktree root>

Verify command: <verify_cmd>

Report format — return exactly:
  status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
  files_changed: [list]
  test_results: <one-line>
  concerns: <if any>
  blockers: <if NEEDS_CONTEXT or BLOCKED>
```

Model the brief on `superpowers:subagent-driven-development`'s implementer-prompt pattern: goal first, constraints explicit, output contract stated up-front.

## Result contract

When `code-impl` returns a summary:

1. **Consume the summary; do not re-read the changed files.** The summary contains all information needed to continue. Re-reading diffs would defeat the token-saving purpose of delegation.
2. Map the status to the next orchestrator action:

| Status | Orchestrator action |
|---|---|
| `DONE` | Mark group complete; proceed to next group or Phase 3. |
| `DONE_WITH_CONCERNS` | Log the concern; decide inline whether to address now or defer. Proceed. |
| `NEEDS_CONTEXT` | Resolve the missing context; re-dispatch with an augmented brief. After two consecutive `NEEDS_CONTEXT` returns on the same group, stop and surface the ambiguity to the user. |
| `BLOCKED` | Stop; diagnose the blocker; decide: fix the brief, fix a dependency, or escalate to the user. |

3. After all groups complete, map to `workflow-development`'s existing "completed by sub-skill" phase-state: if `code-impl` ran `verify_cmd` with evidence, mark Phase 3 "completed by sub-skill" and proceed to Phase 4.

## Parallelism

**Default: sequential dispatch** (same worktree, one group at a time). This eliminates race conditions at zero added complexity.

**Opt-in: per-group worktree isolation** (parallel dispatch). Safe only when **all three** conditions hold:

| Condition | Check | Why |
|---|---|---|
| File-path sets disjoint | No path appears in two groups' `file_set` | Prevents concurrent write conflicts |
| Zero cross-group dependency | No group's output is another's input | Prevents ordering-sensitive failures |
| No shared test target | `verify_cmd`s do not overlap in coverage | Prevents flaky parallel test runs |

If any condition fails → sequential. Document the reason inline so reviewers understand the choice.

## Absolute rules

- `code-impl` never pushes or opens a PR. Delivery (Phase 5) stays single-owner on the orchestrator.
- The orchestrator decides next action from summaries — it does not re-read changed files.
- Each `file_set` must be explicit and disjoint across groups.
- Phase 5 (`swe-workbench:workflow-commit-and-pr`) is always the orchestrator's responsibility.
