# Cost audit — swe-workbench plugin

**Snapshot date:** 2026-05-10  
**Baseline usage observation:** 71% of 24 h Claude usage attributed to swe-workbench; `/swe-workbench:ticket-context` (30%) + subagents (19%) ≈ 49% of total.  
**Purpose:** Data-driven tier assignment. See `cost-tiers.md` for the forward-looking convention.

---

## Agents

At audit time, 14 agents shipped with `model: sonnet`; `product-designer` was added in a subsequent PR. Four (dependency-auditor, product-manager, tech-writer, test-writer) were flipped to `model: haiku` in this PR; see the Recommended tier column. None invoke the `Agent` or `Task` tool (verified by `grep -r 'Agent\|Task' agents/ --include='*.md'` at snapshot) — subagent spawning is exclusively via the orchestrating Claude session.

| Surface | Path | Current model | Spawns subagents? | Recommended tier | Notes |
|---|---|---|---|---|---|
| accessibility-auditor | `agents/accessibility-auditor.md` | sonnet | No | M | Depth-first WCAG reasoning; pattern-matching but requires ARIA/keyboard judgment |
| architect | `agents/architect.md` | sonnet | No | M–L | ADR/RFC authoring; multi-system reasoning; keep on sonnet |
| auditor | `agents/auditor.md` | sonnet | No | M–L | Multi-domain cold-start sweep; calibration and counter-evidence require reasoning |
| debugger | `agents/debugger.md` | sonnet | No | M | Delegates investigation to `systematic-debugging` skill; fix is minimal but judgment-bearing |
| dependency-auditor | `agents/dependency-auditor.md` | sonnet | No | **S → haiku** | Reads manifests, reports versions/licenses; mechanical extraction, low reasoning density. Watch window: GPL/AGPL transitive in MIT projects, SSPL/BUSL/Commons-Clause, per-version license changes, dev-only vs. production viral scope — any relational license judgment that misclassifies to lower severity is a revert trigger. |
| migrator | `agents/migrator.md` | sonnet | No | M–L | Expand-backfill-switch-contract reasoning across deployments; phase correctness is high-stakes |
| performance-tuner | `agents/performance-tuner.md` | sonnet | No | M | Profile-driven; delegates to the `principle-performance` rule; hotspot ranking requires judgment |
| product-designer | `agents/product-designer.md` | sonnet | No | M | Depth-first UX review; usability heuristic judgment and design-system compliance require reasoning |
| product-manager | `agents/product-manager.md` | sonnet | No | **S → haiku** | Formats rough ideas into structured GitHub issues; template discovery + fill is mechanical |
| refactorer | `agents/refactorer.md` | sonnet | No | M | Fowler-catalog steps; behavior-preservation invariant needs correctness judgment |
| reviewer | `agents/reviewer.md` | sonnet | No | M–L | Five-axis PR review (correctness, security, design, tests, comment quality); correctness judgment is high-stakes |
| security-auditor | `agents/security-auditor.md` | sonnet | No | L | OWASP depth-first; exploitability assessment requires strong reasoning |
| senior-engineer | `agents/senior-engineer.md` | sonnet | No | L | Architectural advice; trade-off synthesis; one-way-door assessment |
| tech-writer | `agents/tech-writer.md` | sonnet | No | **S → haiku** | Generates docs from diffs and context; prose transformation with existing tone-matching |
| test-writer | `agents/test-writer.md` | sonnet | No | **S → haiku** | Writes behavioural tests in idiomatic style; mechanical code generation given a spec. Watch: test-writer auto-detects framework, reads existing tests, and loads the `principle-tdd`/`principle-testing` rules — multi-step steps that haiku may skip. Revert if rule loads are skipped or framework detection regresses. |

**Tier S agents (flipped to haiku in this PR):** dependency-auditor, product-manager, tech-writer, test-writer  
**Tier M/L agents (unchanged):** accessibility-auditor, architect, auditor, debugger, migrator, performance-tuner, product-designer, refactorer, reviewer, security-auditor, senior-engineer

---

## Skills

Skills have no `model:` field — they are prose instructions injected into the invoking session's context. Tier here reflects the cognitive load the skill places on the host model, which informs future decisions (e.g., whether to downgrade the invoking session or guard the skill behind a model check).

`principle-*`/`language-*` rows below were skills at snapshot time; they were later converted to plain `rules/*.md` files (no `SKILL.md`, no `Skill`-tool invocation — see `docs/superpowers/specs/2026-07-24-principles-languages-as-rules-design.md`). Paths are updated to the current `rules/<name>.md` location; the cost/tier analysis is unaffected since these were already "N/A model / prose injected into context" at audit time, not independently-dispatched artifacts.

| Surface | Path | Current model | Spawns subagents? | Recommended tier | Notes |
|---|---|---|---|---|---|
| language-bash | `rules/language-bash.md` | N/A | No | M | Language idioms reference |
| language-go | `rules/language-go.md` | N/A | No | M | Language idioms reference |
| language-java | `rules/language-java.md` | N/A | No | M | Language idioms reference |
| language-kotlin | `rules/language-kotlin.md` | N/A | No | M | Language idioms reference |
| language-python | `rules/language-python.md` | N/A | No | M | Language idioms reference |
| language-rust | `rules/language-rust.md` | N/A | No | M | Language idioms reference |
| language-swift | `rules/language-swift.md` | N/A | No | M | Language idioms reference |
| language-typescript | `rules/language-typescript.md` | N/A | No | M | Language idioms reference |
| principle-accessibility | `rules/principle-accessibility.md` | N/A | No | M | WCAG guidance |
| principle-api-design | `rules/principle-api-design.md` | N/A | No | M | REST/gRPC conventions |
| principle-clean-architecture | `rules/principle-clean-architecture.md` | N/A | No | M | Dependency-inversion patterns |
| principle-clean-code | `rules/principle-clean-code.md` | N/A | No | M | Naming / function-size rules |
| principle-concurrency | `rules/principle-concurrency.md` | N/A | No | M | Thread/async safety patterns |
| principle-cost-awareness | `rules/principle-cost-awareness.md` | N/A | No | M | Token-spend heuristics |
| principle-data-modeling | `rules/principle-data-modeling.md` | N/A | No | M | Schema design guidance |
| principle-ddd | `rules/principle-ddd.md` | N/A | No | M | Domain-driven design patterns |
| principle-design-patterns | `rules/principle-design-patterns.md` | N/A | No | M | GoF / structural patterns |
| principle-distributed-systems | `rules/principle-distributed-systems.md` | N/A | No | M | CAP, eventual consistency |
| principle-error-handling | `rules/principle-error-handling.md` | N/A | No | M | Error propagation patterns |
| principle-event-driven | `rules/principle-event-driven.md` | N/A | No | M | Event sourcing / pub-sub |
| principle-i18n | `rules/principle-i18n.md` | N/A | No | M | Localization patterns |
| principle-observability | `rules/principle-observability.md` | N/A | No | M | Logging/tracing/metrics |
| principle-performance | `rules/principle-performance.md` | N/A | No | M | Profile-first optimization |
| principle-product-design | `rules/principle-product-design.md` | N/A | No | M | UX and product design heuristics; usability judgment, visual hierarchy, interaction design |
| principle-resiliency | `rules/principle-resiliency.md` | N/A | No | M | Retry/circuit-breaker patterns |
| principle-security | `rules/principle-security.md` | N/A | No | M | OWASP-aligned security guidance |
| principle-solid | `rules/principle-solid.md` | N/A | No | M | SOLID principles |
| principle-tdd | `rules/principle-tdd.md` | N/A | No | M | Red-green-refactor discipline |
| principle-testing | `rules/principle-testing.md` | N/A | No | M | Test strategy (unit/int/e2e) |
| principle-version-control | `rules/principle-version-control.md` | N/A | No | M | Git workflow conventions |
| ticket-context | `skills/ticket-context/` | N/A | No | **S** | Pure fetch-and-format; no reasoning; high-frequency invocation (30% of session spend at baseline) |
| workflow-bug-triage | `skills/workflow-bug-triage/` | N/A | No | M | Triage orchestration prose |
| workflow-cleanup-merged | `skills/workflow-cleanup-merged/` | N/A | No | M | Branch/worktree cleanup steps |
| workflow-codebase-audit | `skills/workflow-codebase-audit/` | N/A | No | M | Audit orchestration prose |
| workflow-commit-and-pr | `skills/workflow-commit-and-pr/` | N/A | No | M | Commit + PR creation steps |
| workflow-development | `skills/workflow-development/` | N/A | No | L | 5-phase lifecycle orchestration; delegates to multiple sub-skills |
| workflow-pr-review | `skills/workflow-pr-review/` | N/A | No | M | PR review orchestration prose |
| workflow-worktree-session | `skills/workflow-worktree-session/` | N/A | No | M | Worktree session management |

---

## Token-spend hot spots at baseline

| Rank | Surface | Share of 24 h usage | Action taken |
|---|---|---|---|
| 1 | `ticket-context` skill | ~30% | Skill body tightened in this PR |
| 2 | Subagents attributed to swe-workbench | ~19% | 4 Tier-S agents flipped to haiku |
| 3 | All other swe-workbench surfaces | ~22% | No change; monitor. If any single surface exceeds 15% for 3 consecutive days, open a cost-audit follow-up. |

**Post-merge:** compare against this baseline after one representative day of use. Log delta as a comment on issue #160.
