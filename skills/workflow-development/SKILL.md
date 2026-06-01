---
name: workflow-development
description: Development workflow — full lifecycle from Branch → Implement → Verify → Review → Deliver. Activated by /swe-workbench:implement, /swe-workbench:design, /swe-workbench:refactor, /swe-workbench:debug, and /swe-workbench:test when the plan being authored modifies the codebase (Mode A) or when driving an implementation (Mode B). Entry point to execute a written implementation plan end to end: delegates to superpowers:executing-plans and superpowers:subagent-driven-development with the full 5-phase lifecycle. Skip for pure design / analysis output. Can also be invoked directly to author a Workflow section, run the 5-phase implementation flow, or orchestrate parallel agents (Mode C).
orchestrator: true
---

# Development Workflow

Single source of truth for how development work flows. Three modes:

- **Mode A (Plan Writing):** Embed a `## Workflow` section into plans using `templates/plan-workflow-section.md`
- **Mode B (Implementation):** Guide step-by-step execution through all 5 phases
- **Mode C (Orchestration):** Coordinate multiple parallel agents across dependency rounds — see `orchestration.md`

**Announce at start:** "I'm using the development skill to [write the workflow section / guide this implementation]."

## When This Skill Activates

- **Mode A:** Writing or finalizing an implementation plan (before `ExitPlanMode`)
- **Mode B:** User says "implement this", "build this", "execute this plan", "run the implementation plan end to end" — any branch → code → deliver flow. For focused bug diagnosis prefer `/swe-workbench:debug` (invokes the `debugger` subagent, which composes `superpowers:systematic-debugging`); escalate here when the fix needs the full 5-phase lifecycle.
  - **Prefer entering here rather than calling `superpowers:executing-plans` directly** — Phase 2 already delegates to it while adding the surrounding Branch → Verify → Review → Deliver lifecycle.
- **Mode C:** User says "orchestrate these issues", "run in parallel", multi-issue campaigns with >3 issues

## Sub-Skill Integration Map

```
Mode B — Single Implementation:

  Phase 1 (Branch)    → rimba add <task> (if rimba on PATH) OR superpowers:using-git-worktrees (fallback)
  Phase 2 (Implement) → superpowers:executing-plans OR superpowers:subagent-driven-development
                          └─ swe-workbench:principle-tdd (per unit)
                          └─ swe-workbench:workflow-delegated-implementation (scope/complexity warrants isolation)
  Phase 3 (Verify)    → superpowers:verification-before-completion
  Phase 4 (Review)    → superpowers:requesting-code-review (plan-alignment)
                          └─ swe-workbench:reviewer (diff correctness/security/design)
  Phase 5 (Deliver)   → swe-workbench:workflow-commit-and-pr

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

**Detection markers** used by `templates/plan-workflow-section.md` — substitute every `[[detect:KEY]]` before saving the plan:

- `branch-convention` — from `git branch -a`
- `commit-style` — from `git log --oneline -20`
- `imports-command` — from Makefile `imports` target or language-marker fallback below
- `format-command` — from Makefile `format` target or language-marker fallback below
- `lint-command` — from Makefile `lint` target or language-marker fallback below
- `test-command` — from Makefile `test` target or language-marker fallback below
- `quality-command` — from Makefile `quality` target, project-script, or language-marker fallback below. Optional — if absent and no config is detected, skip the Quality stage with a note.
- `pr-template-path` — absolute path of the detected PR template, or `"none — use default format"`

**Language marker fallback (if no Makefile):**

| Marker | Imports | Format | Lint | Test |
|--------|---------|--------|------|------|
| `go.mod` | `goimports -w .` | `gofmt -w .` | `golangci-lint run` | `go test ./...` |
| `package.json` | `npx organize-imports-cli` (always works); or `eslint --fix` if `eslint-plugin-import` / `@typescript-eslint/consistent-type-imports` configured | check `scripts.format`/`prettier` | check `scripts.lint`/`eslint` | check `scripts.test` |
| `Cargo.toml` | `cargo fix --allow-dirty` (removes unused imports — review output before staging); configure `imports_granularity` in `rustfmt.toml` then `cargo fmt` | `cargo fmt` | `cargo clippy` | `cargo test` |
| `pyproject.toml` | `ruff check --select I --fix` (legacy: `isort .` + `autoflake -r --remove-all-unused-imports .`) | `ruff format` or `black .` | `ruff check` | `pytest` |
| `pom.xml` | `mvn spotless:apply` (requires import-ordering rules in Spotless config; for unused-import removal add `impsort-maven-plugin`) | `mvn spotless:apply` | `mvn checkstyle:check` (requires plugin; Gradle: `./gradlew check`) | `mvn test` |

> **`quality-command` fallback** is in the table below — intentionally separate because Quality is multi-tool by nature and a single cell would be unreadably wide.

**Quality stage fallback (multi-tool — wire whichever subset the project enforces):**

| Marker | Tool examples (complexity • duplication • length / maintainability) |
|--------|---------------------------------------------------------------------|
| `go.mod` | `gocyclo -over 15 .` • `dupl -t 50 ./...` • `gocognit -over 15 .` |
| `package.json` | `eslint` with `eslint-plugin-sonarjs` • `jscpd` • `es6-plato` (maintainability index; maintained fork of plato, Node 18+ compatible) |
| `Cargo.toml` | `cargo clippy -- -W clippy::cognitive_complexity` • (duplication: no OSS first-party tool; `jscpd` covers cross-language including Rust; `simian` is cross-language but commercial) • `cargo clippy -- -W clippy::too_many_lines` (per-function length; no file-level enforcer in first-party Rust) |
| `pyproject.toml` | `radon cc -n B -s` (grade ≥ B = complexity ≥ 6) and `lizard -CCN 15 -L 50` • `pylint --disable=all --enable=duplicate-code` • `radon mi -n B` |
| `pom.xml` | `mvn pmd:check` • `mvn pmd:cpd-check` • `checkstyle` (FileLengthCheck, MethodLengthCheck) |

**PR template:** check `cat .github/pull_request_template.md 2>/dev/null` (and common variants: `.github/PULL_REQUEST_TEMPLATE.md`, `docs/pull_request_template.md`). If found, record the **absolute path** — pass it to `gh pr create --body-file <path>` in Phase 5. Before invoking, replace the literal `Closes #` placeholder with the resolved issue (`Closes #123`) or remove it and write a standalone `Issue: N/A — <one-line reason>` line. Never leave `Closes #` empty.

## The 5 Phases

---

### Phase 1: Branch

**Goal:** Isolated workspace with clean baseline.

**Worktree provider detection:**

```sh
# Prefer rimba MCP server when active in the session (no shell needed).
# Otherwise resolve the binary: PATH first, then common install locations.
# NOTE: use `rimba version` (subcommand) to print the version; `rimba --version`
#       is not a recognised flag and exits non-zero.
RIMBA=$(command -v rimba 2>/dev/null \
  || { [ -x "$HOME/.local/bin/rimba" ] && echo "$HOME/.local/bin/rimba"; } \
  || { [ -x "$HOME/go/bin/rimba" ]     && echo "$HOME/go/bin/rimba"; } \
  || true)
```

- **rimba MCP server active:** invoke the `add` tool on it (`rimba mcp`) — no shell process needed. Use `add pr:<num>` when implementing from a PR number.
- **`$RIMBA` non-empty (binary found):** run `$RIMBA add [<service>/]<task> [--flag]` (or `$RIMBA add pr:<num> --task "<label>"` for a PR). Rimba handles branch-prefix conventions (`feature/`, `bugfix/`, `hotfix/`, `docs/`, `test/`, `chore/`), `.env`/`.tool-versions`/`.vscode` copying, `post_create` hooks, and lockfile sharing.
- **Promote work already started** — if you began editing on the current branch in the main checkout (not the default branch), `$RIMBA add branch:<current-branch>` moves that work into its own worktree, transferring dirty changes via `git stash`. `--source` is not valid in this mode.
- **rimba absent:** invoke `superpowers:using-git-worktrees` exactly as today.

**Picking the branch-prefix flag** — derive from the commit-tag the change will carry (see `workflow-commit-and-pr` for the full taxonomy):

| Work type | rimba flag | Branch prefix | Commit-tag |
|---|---|---|---|
| New feature *(default)* | *(none)* | `feature/<task>` | `[feat]` |
| Bug fix | `--bugfix` | `bugfix/<task>` | `[fix]` |
| Hotfix | `--hotfix` | `hotfix/<task>` | `[hotfix]` |
| Documentation | `--docs` | `docs/<task>` | `[docs]` |
| Tests | `--test` | `test/<task>` | `[test]` |
| Chore / tooling | `--chore` | `chore/<task>` | `[chore]` |

Examples: `$RIMBA add auth-redirect --bugfix` → `bugfix/auth-redirect`; `$RIMBA add ci-matrix --chore` → `chore/ci-matrix`.

**Monorepo scope** — in a monorepo, prefix the task with the service or package name using `<service>/<task>`. The type flag still controls the branch prefix:

- `$RIMBA add backend-api/auth-redirect --bugfix` → `bugfix/backend-api/auth-redirect`
- `$RIMBA add frontend/dark-mode` → `feature/frontend/dark-mode`

Use the service scope whenever the work is clearly contained within one module — it groups branches and makes worktree paths self-descriptive. For cross-cutting changes, inspect the planned file edits and pick the service where the majority of changes land. If two services tie, prefer the service that owns the primary interface changed (e.g. the API layer for a contract change, the UI layer for a rendering change); only omit the scope entirely if no service file is touched at all (e.g. a root-only CI config change).

**Post-create timing** — `rimba add` runs dependency install and `post_create` hooks *after* creating the worktree (steps that can take minutes for Go/Node/Python projects). The session must not move to Phase 2 until `rimba add` prints `Path: <abs-path>` and exits.

- **Deps required (most stacks):** omit `--skip-deps`/`--skip-hooks` and wait for `rimba add` to complete before entering Phase 2. This applies regardless of whether the plan is TDD-first — if the test suite needs installed packages, rimba must finish first.
- **No deps needed:** pass `--skip-deps` and `--skip-hooks` only when the test suite requires no installation step (e.g. pure shell scripts, documentation assertion tests). Never skip deps and then reinstall them manually — rimba's pipeline already handles it correctly.

Verify baseline tests pass before writing any code.

---

### Phase 2: Implement

**Goal:** Write code following the plan, committing incrementally.

Choose execution strategy:
- **Sequential or separate session** → invoke `superpowers:executing-plans`
- **Independent tasks, same session** → invoke `superpowers:subagent-driven-development`
- **No plan / ad-hoc** → implement directly with `swe-workbench:principle-tdd` per unit
- **Scope/complexity warrants isolation** → invoke `swe-workbench:workflow-delegated-implementation` to group changes and dispatch each cohesive group to a focused `code-impl` sub-agent; consume the summary (not the diff) to stay lean

If a delegated `code-impl` run returns with verification evidence, mark Phase 3 "completed by sub-skill" per the deduplication rule above.

Commit logically grouped changes as you go. Never bundle unrelated changes.

| Commit type | Contains |
|---|---|
| Infrastructure | Config, dependencies, build changes |
| Core logic | Main feature/fix implementation |
| Tests | Test files and test utilities |
| Wiring | Integration, routing, CLI registration |

---

### Phase 3: Verify

**Goal:** Confirm imports, format, quality, lint, and test all pass with evidence.

Run in order — **Imports → Format → Quality → Lint → Test**. Imports come first because organizers
(`goimports`, `ruff check --select I --fix`, `organize-imports-cli`, `spotless`) reshape lines that
the formatter then normalises; reversing the order causes spurious rewrites on the next pass.
Quality runs after Format so metrics evaluate normalised code, and before Lint so threshold violations
surface as a distinct signal rather than mixed into lint noise. **Quality is optional** — if no
`quality-command` is detected and the project has no complexity/duplication/length config, skip the
stage with a note in the evidence block.

Invoke `superpowers:verification-before-completion`.

**Skip condition:** If Phase 2 sub-skill already ran full verification (imports + format + quality + lint + test) with evidence, mark as "completed by sub-skill" and proceed.

---

### Phase 4: Review

**Goal:** Catch design and quality issues before delivery.

Dispatch both reviewers — they answer different questions:
- `superpowers:requesting-code-review` — plan-alignment: does this match the plan and meet standards?
- `swe-workbench:reviewer` subagent — diff review: correctness, security, design, test gaps in `Severity | File:Line | Issue | Why it matters | Suggested fix` format

Act on feedback:
- **Critical/Important:** fix → re-verify (Phase 3) → re-review
- **Minor:** note or fix inline, proceed

**Skip condition:** If Phase 2 sub-skill already ran two-stage code review with evidence, mark as "completed by sub-skill" and proceed.

---

### Phase 5: Deliver

**Goal:** Push branch and create PR.

Invoke `swe-workbench:workflow-commit-and-pr`.

**PR template rule:** if a template was detected in Project Detection, use `gh pr create --body-file [[detect:pr-template-path]]` — fill every section and substitute the `Closes #` placeholder before invoking. Do **not** fall through to a heredoc body when a template exists. Only use the heredoc fallback if no template was found.

---

## Optional deeper passes

Two existing skills provide deeper verification when warranted — invoke ad hoc outside the 5-phase core loop:

- `swe-workbench:workflow-codebase-audit` — multi-axis structural audit. Run pre-release or when onboarding a new codebase.
- `swe-workbench:security-review` — depth-first OWASP / secret-leak review. Run pre-merge for diffs touching auth, input parsing, secrets, or network surfaces.

---

## Plan-Time Behavior (Mode A)

**Gate:** Before rendering the Workflow section, confirm the plan introduces file edits (fix / make / implement). If the plan is a pure design recommendation or analysis with no codebase changes, return without modifying the plan.

When writing or finalizing a plan, add a `## Workflow` section using the template at `templates/plan-workflow-section.md`. Substitute every `[[detect:KEY]]` marker with concrete values from Project Detection. **Before saving, grep your rendered draft for `[[detect:` — if any match remains, you skipped Project Detection; redo it.**

## Implementation-Time Behavior (Mode B)

1. **Announce transitions**: `Phase N complete — <summary>. Moving to Phase N+1: <name>.`
2. **Checkpoint**: after each phase transition, write the workflow state file so the session can survive auto-compaction (see `docs/workflow-state.md` for the schema and path). At Phase 5 success, delete the state file.
3. **Delegate to sub-skills**: don't re-implement what a sub-skill already does.
4. **Track phase state** — sub-skill completed Phases 3 or 4 with evidence → mark them "completed by sub-skill".
5. **Handle failures and no phase skipping** combined:

| Phase | Failure | Skip condition |
|-------|---------|----------------|
| 1 | Tests fail on baseline → report, ask to proceed | When caller passes `skip-phase-1: <rationale>` — branch already exists (e.g. invoked by `workflow-extend`) |
| 2 | Implementation blocked → stop, ask for clarification | Never |
| 3 | Verification fails → fix, re-run from imports | Sub-skill verified with evidence |
| 4 | Critical review issues → fix, re-verify, re-review | Sub-skill reviewed with evidence |
| 5 | Push/PR fails → diagnose, report | Never |

## Guardrails

### Common Mistakes

| Mistake | Fix |
|---------|-----|
| Skip verification, go straight to review | Always verify first (Phase 3 before 4) |
| Run only tests (skip imports/format/quality/lint) | Run all five, in order |
| Single giant commit | Group by logical change |
| Guess at branch/commit conventions | Detect from `git branch -a` and `git log` first |
| Plan that introduces file edits without Workflow section | Always add the Workflow section (Mode A) — skip only for pure design / analysis output |
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
| "Tests passed, good enough" | Run imports, format, quality, and lint too |
| "Review is overkill for this" | Small changes have bugs too. Review. |
| "I'll just commit everything together" | Split into logical commits |
| "Phase 2 sub-skill did everything" | Verify it provided evidence for Phases 3-4 |
| "This is a small fix, no need for the full lifecycle" | Small fixes still need verify + review |
| "The plan doesn't need a Workflow section" | If the plan introduces file edits, it does. Add one (Mode A). Skip only for pure design / analysis output. |
