---
name: development
description: Use when implementing features, fixing bugs, or executing plans — defines the full development lifecycle (Branch → Implement → Verify → Review → Deliver) and embeds workflow steps into plans
---

# Development Workflow

Single source of truth for how development work flows. Three modes:

- **Mode A (Plan Writing):** Embed a `## Workflow` section into plans using `templates/plan-workflow-section.md`
- **Mode B (Implementation):** Guide step-by-step execution through all 5 phases
- **Mode C (Orchestration):** Coordinate multiple parallel agents across dependency rounds — see `orchestration.md`

**Announce at start:** "I'm using the development skill to [write the workflow section / guide this implementation]."

## When This Skill Activates

- **Mode A:** Writing or finalizing an implementation plan (before `ExitPlanMode`)
- **Mode B:** User says "implement this", "build this", "fix this" — any branch → code → deliver flow
- **Mode C:** User says "orchestrate these issues", "run in parallel", multi-issue campaigns with >3 issues

## Sub-Skill Integration Map

```
Mode B — Single Implementation:

  Phase 1 (Branch)    → superpowers:using-git-worktrees
  Phase 2 (Implement) → superpowers:executing-plans OR superpowers:subagent-driven-development
                          └─ superpowers:test-driven-development (per unit)
  Phase 3 (Verify)    → superpowers:verification-before-completion
  Phase 4 (Review)    → superpowers:requesting-code-review
                          └─ superpowers:code-reviewer (plan-alignment)
                          └─ swe-workbench:reviewer (diff correctness/security/design)
  Phase 5 (Deliver)   → superpowers:finishing-a-development-branch

Mode C — Orchestration: see orchestration.md
```

**Deduplication rule:** If a Phase 2 sub-skill already ran verification or review with evidence, mark that phase "completed by sub-skill" and proceed.

## Project Detection

Run during activation to populate workflow with project-specific values.

```bash
git branch -a && git log --oneline -20   # branch convention + commit style
grep -E '^[a-zA-Z_-]+:' Makefile 2>/dev/null   # available make targets
```

Also check CLAUDE.md for project-specific conventions.

**Language marker fallback (if no Makefile):**

| Marker | Format | Lint | Test |
|--------|--------|------|------|
| `go.mod` | `gofmt -w .` | `golangci-lint run` | `go test ./...` |
| `package.json` | check `scripts.format`/`prettier` | check `scripts.lint`/`eslint` | check `scripts.test` |
| `Cargo.toml` | `cargo fmt` | `cargo clippy` | `cargo test` |
| `pyproject.toml` | `ruff format` or `black .` | `ruff check` | `pytest` |

**PR template:** check `cat .github/pull_request_template.md 2>/dev/null` (and common variants). If it exists, **use it and fill every section**.

## The 5 Phases

---

### Phase 1: Branch

**Goal:** Isolated workspace with clean baseline.

Invoke `superpowers:using-git-worktrees` for workspace setup. Verify baseline tests pass before writing any code.

---

### Phase 2: Implement

**Goal:** Write code following the plan, committing incrementally.

Choose execution strategy:
- **Sequential or separate session** → invoke `superpowers:executing-plans`
- **Independent tasks, same session** → invoke `superpowers:subagent-driven-development`
- **No plan / ad-hoc** → implement directly with `superpowers:test-driven-development` per unit

Commit logically grouped changes as you go — infrastructure, core logic, tests, and wiring as separate commits. Never bundle unrelated changes.

---

### Phase 3: Verify

**Goal:** Confirm format, lint, and test all pass with evidence.

Invoke `superpowers:verification-before-completion`.

**Skip condition:** If Phase 2 sub-skill already ran full verification (format + lint + test) with evidence, mark as "completed by sub-skill" and proceed.

---

### Phase 4: Review

**Goal:** Catch design and quality issues before delivery.

Dispatch both reviewers — they answer different questions:
- `superpowers:code-reviewer` — plan-alignment: does this match the plan and meet standards?
- `swe-workbench:reviewer` subagent — diff review: correctness, security, design, test gaps in `Severity | File:Line | Issue | Why it matters | Suggested fix` format

Act on feedback:
- **Critical/Important:** fix → re-verify (Phase 3) → re-review
- **Minor:** note or fix inline, proceed

**Skip condition:** If Phase 2 sub-skill already ran two-stage code review with evidence, mark as "completed by sub-skill" and proceed.

---

### Phase 5: Deliver

**Goal:** Push branch and create PR.

Invoke `superpowers:finishing-a-development-branch`.

**PR template rule:** if a template was detected in Project Detection, use it and fill every section. Skipping sections signals incomplete work to reviewers.

---

## Plan-Time Behavior (Mode A)

When writing or finalizing a plan, add a `## Workflow` section using the template at `templates/plan-workflow-section.md`. Substitute detected commands before saving.

## Implementation-Time Behavior (Mode B)

1. **Announce transitions**: `Phase N complete — <summary>. Moving to Phase N+1: <name>.`
2. **Delegate to sub-skills**: don't re-implement what a sub-skill already does.
3. **Track phase state** — sub-skill completed Phases 3 or 4 with evidence → mark them "completed by sub-skill".
4. **Handle failures and no phase skipping** combined:

| Phase | Failure | Skip condition |
|-------|---------|----------------|
| 1 | Tests fail on baseline → report, ask to proceed | Never |
| 2 | Implementation blocked → stop, ask for clarification | Never |
| 3 | Verification fails → fix, re-run from format | Sub-skill verified with evidence |
| 4 | Critical review issues → fix, re-verify, re-review | Sub-skill reviewed with evidence |
| 5 | Push/PR fails → diagnose, report | Never |

## Guardrails

### Common Mistakes

| Mistake | Fix |
|---------|-----|
| Skip verification, go straight to review | Always verify first (Phase 3 before 4) |
| Run only tests (skip format/lint) | Run all three, in order |
| Single giant commit | Group by logical change |
| Guess at branch/commit conventions | Detect from `git branch -a` and `git log` first |
| Plan without Workflow section | Always add the Workflow section (Mode A) |
| Jump straight to coding | Always start at Phase 1 |
| Ignore PR template, use generic format | Check for PR template first; fill every section |

### Red Flags — Never

- Implement directly on main/master without explicit user consent
- Skip verification for any reason
- Proceed with unresolved critical/important review issues
- Force-push without explicit user request
- Commit files that may contain secrets (`.env`, credentials)

### If You Catch Yourself Thinking…

| Thought | Action |
|---------|--------|
| "Tests passed, good enough" | Run format AND lint too |
| "Review is overkill for this" | Small changes have bugs too. Review. |
| "I'll just commit everything together" | Split into logical commits |
| "Phase 2 sub-skill did everything" | Verify it provided evidence for Phases 3-4 |
| "This is a small fix, no need for the full lifecycle" | Small fixes still need verify + review |
| "The plan doesn't need a Workflow section" | It always does. Add one (Mode A). |
