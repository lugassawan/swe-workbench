# Cost audit — swe-workbench plugin

**Snapshot date:** 2026-05-10  
**Baseline usage observation:** 71% of 24 h Claude usage attributed to swe-workbench; `/swe-workbench:ticket-context` (30%) + subagents (19%) ≈ 49% of total.  
**Purpose:** Data-driven tier assignment. See `cost-tiers.md` for the forward-looking convention.

---

## Agents

All 14 agents shipped with `model: sonnet` at audit time. Four (dependency-auditor, product-manager, tech-writer, test-writer) were flipped to `model: haiku` in this PR; see the Recommended tier column. None invoke the `Agent` or `Task` tool (verified by `grep -r 'Agent\|Task' agents/ --include='*.md'` at snapshot) — subagent spawning is exclusively via the orchestrating Claude session.

| Surface | Path | Current model | Spawns subagents? | Recommended tier | Notes |
|---|---|---|---|---|---|
| accessibility-auditor | `agents/accessibility-auditor.md` | sonnet | No | M | Depth-first WCAG reasoning; pattern-matching but requires ARIA/keyboard judgment |
| architect | `agents/architect.md` | sonnet | No | M–L | ADR/RFC authoring; multi-system reasoning; keep on sonnet |
| auditor | `agents/auditor.md` | sonnet | No | M–L | Multi-domain cold-start sweep; calibration and counter-evidence require reasoning |
| debugger | `agents/debugger.md` | sonnet | No | M | Delegates investigation to `systematic-debugging` skill; fix is minimal but judgment-bearing |
| dependency-auditor | `agents/dependency-auditor.md` | sonnet | No | **S → haiku** | Reads manifests, reports versions/licenses; mechanical extraction, low reasoning density. Watch window: GPL/AGPL transitive in MIT projects, SSPL/BUSL/Commons-Clause, per-version license changes, dev-only vs. production viral scope — any relational license judgment that misclassifies to lower severity is a revert trigger. |
| migrator | `agents/migrator.md` | sonnet | No | M–L | Expand-backfill-switch-contract reasoning across deployments; phase correctness is high-stakes |
| performance-tuner | `agents/performance-tuner.md` | sonnet | No | M | Profile-driven; delegates to `principle-performance` skill; hotspot ranking requires judgment |
| product-designer | `agents/product-designer.md` | sonnet | No | M | Depth-first UX review; usability heuristic judgment and design-system compliance require reasoning |
| product-manager | `agents/product-manager.md` | sonnet | No | **S → haiku** | Formats rough ideas into structured GitHub issues; template discovery + fill is mechanical |
| refactorer | `agents/refactorer.md` | sonnet | No | M | Fowler-catalog steps; behavior-preservation invariant needs correctness judgment |
| reviewer | `agents/reviewer.md` | sonnet | No | M–L | Four-axis PR review (correctness, security, design, tests); correctness judgment is high-stakes |
| security-auditor | `agents/security-auditor.md` | sonnet | No | L | OWASP depth-first; exploitability assessment requires strong reasoning |
| senior-engineer | `agents/senior-engineer.md` | sonnet | No | L | Architectural advice; trade-off synthesis; one-way-door assessment |
| tech-writer | `agents/tech-writer.md` | sonnet | No | **S → haiku** | Generates docs from diffs and context; prose transformation with existing tone-matching |
| test-writer | `agents/test-writer.md` | sonnet | No | **S → haiku** | Writes behavioural tests in idiomatic style; mechanical code generation given a spec. Watch: test-writer auto-detects framework, reads existing tests, and invokes `principle-tdd`/`principle-testing` skills — multi-step steps that haiku may skip. Revert if Skill invocations are skipped or framework detection regresses. |

**Tier S agents (flipped to haiku in this PR):** dependency-auditor, product-manager, tech-writer, test-writer  
**Tier M/L agents (unchanged):** accessibility-auditor, architect, auditor, debugger, migrator, performance-tuner, refactorer, reviewer, security-auditor, senior-engineer

---

## Skills

Skills have no `model:` field — they are prose instructions injected into the invoking session's context. Tier here reflects the cognitive load the skill places on the host model, which informs future decisions (e.g., whether to downgrade the invoking session or guard the skill behind a model check).

| Surface | Path | Current model | Spawns subagents? | Recommended tier | Notes |
|---|---|---|---|---|---|
| language-bash | `skills/language-bash/` | N/A | No | M | Language idioms reference |
| language-go | `skills/language-go/` | N/A | No | M | Language idioms reference |
| language-java | `skills/language-java/` | N/A | No | M | Language idioms reference |
| language-kotlin | `skills/language-kotlin/` | N/A | No | M | Language idioms reference |
| language-python | `skills/language-python/` | N/A | No | M | Language idioms reference |
| language-rust | `skills/language-rust/` | N/A | No | M | Language idioms reference |
| language-swift | `skills/language-swift/` | N/A | No | M | Language idioms reference |
| language-typescript | `skills/language-typescript/` | N/A | No | M | Language idioms reference |
| principle-accessibility | `skills/principle-accessibility/` | N/A | No | M | WCAG guidance |
| principle-api-design | `skills/principle-api-design/` | N/A | No | M | REST/gRPC conventions |
| principle-clean-architecture | `skills/principle-clean-architecture/` | N/A | No | M | Dependency-inversion patterns |
| principle-clean-code | `skills/principle-clean-code/` | N/A | No | M | Naming / function-size rules |
| principle-concurrency | `skills/principle-concurrency/` | N/A | No | M | Thread/async safety patterns |
| principle-cost-awareness | `skills/principle-cost-awareness/` | N/A | No | M | Token-spend heuristics |
| principle-data-modeling | `skills/principle-data-modeling/` | N/A | No | M | Schema design guidance |
| principle-ddd | `skills/principle-ddd/` | N/A | No | M | Domain-driven design patterns |
| principle-design-patterns | `skills/principle-design-patterns/` | N/A | No | M | GoF / structural patterns |
| principle-distributed-systems | `skills/principle-distributed-systems/` | N/A | No | M | CAP, eventual consistency |
| principle-error-handling | `skills/principle-error-handling/` | N/A | No | M | Error propagation patterns |
| principle-event-driven | `skills/principle-event-driven/` | N/A | No | M | Event sourcing / pub-sub |
| principle-i18n | `skills/principle-i18n/` | N/A | No | M | Localization patterns |
| principle-observability | `skills/principle-observability/` | N/A | No | M | Logging/tracing/metrics |
| principle-performance | `skills/principle-performance/` | N/A | No | M | Profile-first optimization |
| principle-resiliency | `skills/principle-resiliency/` | N/A | No | M | Retry/circuit-breaker patterns |
| principle-security | `skills/principle-security/` | N/A | No | M | OWASP-aligned security guidance |
| principle-solid | `skills/principle-solid/` | N/A | No | M | SOLID principles |
| principle-tdd | `skills/principle-tdd/` | N/A | No | M | Red-green-refactor discipline |
| principle-testing | `skills/principle-testing/` | N/A | No | M | Test strategy (unit/int/e2e) |
| principle-version-control | `skills/principle-version-control/` | N/A | No | M | Git workflow conventions |
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
