# Catalog

## Commands

| Command | Purpose |
|---|---|
| `/swe-workbench:review [--mode <general\|security\|a11y\|deps\|perf>]` | Review the current git diff — auditor selected by `--mode` (general, security, a11y, deps, perf) or auto-inferred from the diff when omitted. PR number arg unchanged. |
| `/swe-workbench:security-review` | Alias for `/swe-workbench:review --mode security`. Kept for backward compat. |
| `/swe-workbench:design <question>` | Consult the senior-engineer subagent for an architectural decision. |
| `/swe-workbench:architect <decision>` | Author an ADR, RFC, or cross-service contract via the architect subagent. Use when the output must be a written decision record — service decomposition, multi-system tech selection, cross-team contract — not advice about existing code. |
| `/swe-workbench:refactor <target>` | Behavior-preserving refactor via Fowler's catalog. |
| `/swe-workbench:migrate <description>` | Multi-deployment migration via expand → backfill → dual-write → switch → contract. Use when a single revertable commit will not do. |
| `/swe-workbench:debug <symptom>` | Diagnose a bug or failing test via systematic-debugging, then minimal fix + regression test. |
| `/swe-workbench:test <target>` | Write focused, behavioural tests in the target language's idiom. |
| `/swe-workbench:implement <ticket or description>` | Drive a feature end-to-end — branch, plan, TDD build, verify, review, PR. Orchestrates the full 5-phase `workflow-development` lifecycle. |
| `/swe-workbench:capture <one-line thought>` | Capture an idea, bug, or improvement as a well-framed GitHub issue via the `product-manager` subagent. Auth + repo detection, product framing, duplicate scan, draft preview, and user-confirm gate before filing. |
| `/swe-workbench:extend <sub-idea>` | Capture a mid-PR sub-idea and implement it onto the open PR's branch — no new branch, no new PR. Preserves Verify → Review → Deliver. |
| `/swe-workbench:cleanup-merged [PR number]` | Remove the worktree, local branch, and remote branch for a merged PR. Defaults to the current branch. Squash-merge safe. |

## Subagents

| Agent | When to invoke |
|---|---|
| `reviewer` | PR review, diff audit, post-feature sanity check. |
| `security-auditor` | Depth-first security audit of a diff or file (OWASP Top 10, secrets, dependency CVEs). |
| `architect` | Authoring ADRs, RFCs, and cross-service contracts for decisions that predate any codebase — service decomposition, multi-system tech selection, cross-team contract. Prefer over `senior-engineer` when the output must be a durable written artifact, not advice about existing code. Invoked by `/swe-workbench:architect`. |
| `senior-engineer` | Architecture decisions, service scoping, tradeoff analysis. |
| `refactorer` | Cleaning up smells before adding a feature. |
| `debugger` | Bug diagnosis and minimal fix — composes `superpowers:systematic-debugging`, layers principle lens. |
| `test-writer` | Authoring tests for an existing function, module, or change set. |
| `test-reviewer` | Auditing existing tests for flakiness, over-mocking, behaviour-vs-implementation drift, and coverage gaps. |
| `product-manager` | Drafts a well-framed GitHub issue from a raw idea — product framing (problem, value, RICE-lite), template detection, duplicate scan, and confirm gate. Invoked by `/swe-workbench:capture`. |
| `tech-writer` | Generates README sections, ADRs, ARCHITECTURE/OVERVIEW, and non-obvious inline comments — style-aware, reads existing docs first. |
| `migrator` | Plan and execute a multi-deployment migration: DB schema, framework upgrade, runtime, API/contract, or event-schema. Produces a five-phase (Expand → Backfill → Dual-write → Switch → Contract) plan with rollback gates. Invoked by `/swe-workbench:migrate`. |
| `performance-tuner` | Profile-driven hotspot triage — ranks bottlenecks from a flame graph or benchmark and recommends targeted optimizations. Refuses speculative optimization without profiling evidence. |

## Skills

### Principles — consulted by reasoning agents when relevant triggers apply

| Skill | Triggers |
|---|---|
| `principle-clean-architecture` | "clean architecture", "hexagonal", "ports and adapters", "dependency rule", "layering". |
| `principle-ddd` | "DDD", "domain-driven", "bounded context", "aggregate", "value object", "ubiquitous language". |
| `principle-solid` | "SOLID", "single responsibility", "open-closed", "Liskov", "interface segregation", "dependency inversion". |
| `principle-tdd` | "TDD", "test-driven", "red green refactor", "unit test", "test first". |
| `principle-testing` | "test pyramid", "test double", "mock", "stub", "fake", "fixture", "coverage", "mutation testing", "flaky", "contract test", "property-based test", "characterization test". |
| `principle-design-patterns` | "design pattern", "strategy", "factory", "observer", "decorator", "adapter". |
| `principle-clean-code` | "clean code", "function length", "naming", "DRY", "KISS", "YAGNI", "abstraction level", "error handling". |
| `principle-code-review` | "code review checklist", "PR review heuristics", "review comment", "review finding", "nitpick filtering", "reviewing a diff". |
| `principle-refactoring` | "refactor", "Fowler", "Extract Function", "Inline Variable", "Move Function", "smell", "Long Method", "Feature Envy", "Data Clumps", "Primitive Obsession", "characterization test", "behavior-preserving". |
| `principle-observability` | "structured logs", "application metrics", "distributed traces", "span", "OpenTelemetry", "SLO", "SLI", "RED method", "USE method", "cardinality", "structured logging". |
| `principle-api-design` | "api versioning", "idempotency", "idempotency key", "pagination", "cursor pagination", "error shape", "REST vs RPC", "event-driven", "API deprecation", "API contract". |
| `principle-error-handling` | "errors as values", "Result type", "exception handling", "retry", "exponential backoff", "jitter", "circuit breaker", "fail fast", "fail soft", "idempotent retry", "error wrapping", "timeouts", "deadlines". |
| `principle-concurrency` | "race condition", "deadlock", "livelock", "structured concurrency", "cancellation", "backpressure", "mutex vs channel", "actor model", "atomics", "memory model". |
| `principle-cost-awareness` | "cloud cost", "FinOps", "egress", "right-sizing", "scale-to-zero", "cost-per-request", "storage tier", "log volume", "cardinality cost". |
| `principle-data-modeling` | "schema design", "data model", "normalization", "denormalization", "indexing", "hot key", "hot partition", "schema evolution", "expand contract", "query-first", "storage paradigm", "relational vs document", "TTL", "archival". |
| `principle-security` | "auth", "authn", "authz", "trust boundary", "input validation", "SSRF", "CSRF", "session", "JWT", "TLS", "secret", "encrypt". |

### Languages — auto-load by file type

| Skill | Triggers |
|---|---|
| `language-sql` | `.sql` files, migration files; keywords: SQL, SELECT, JOIN, EXPLAIN, CTE, window function, transaction isolation, deadlock, pagination. |
| `language-go` | `.go` files, `go.mod`, `go.sum`, keywords: Go, Golang, goroutine, channel, context. |
| `language-java` | `.java` files, `pom.xml`, `build.gradle`, keywords: Java, JVM, Spring, Maven, Gradle, records, sealed classes, virtual threads. |
| `language-kotlin` | `.kt` files, `build.gradle.kts`, keywords: Kotlin, coroutines, suspend, StateFlow, sealed interface, Kotlin DSL. |
| `language-rust` | `.rs` files, `Cargo.toml`, keywords: Rust, cargo, ownership, borrow checker, trait, lifetime. |
| `language-swift` | `.swift` files, `Package.swift`, keywords: Swift, SwiftUI, actors, async/await, Sendable, Result builders, Swift Package Manager. |
| `language-typescript` | `.ts`, `.tsx`, `.js`, `.jsx`, `package.json`, keywords: TypeScript, Node, tsconfig. |
| `language-python` | `.py` files, `pyproject.toml`, `requirements.txt`, keywords: Python, pytest, asyncio, dataclass, type hints, virtualenv. |

### Workflows — auto-load during implementation

| Skill | Triggers | Delegation model |
|---|---|---|
| `workflow-development` | "implement this", "build this", "fix this bug", "execute plan", "orchestrate these issues". | Wraps the 5-phase lifecycle (Branch → Implement → Verify → Review → Deliver). Phase 1 prefers `rimba add <task>` when rimba is available; falls back to `superpowers:using-git-worktrees`. Phase 2 applies `swe-workbench:principle-tdd` per unit (via `superpowers:executing-plans` or `superpowers:subagent-driven-development`). Phase 3 invokes `superpowers:verification-before-completion`. Phase 4 dispatches `superpowers:code-reviewer` (plan-alignment) and `swe-workbench:reviewer` (diff quality). Phase 5 invokes `swe-workbench:workflow-commit-and-pr`. Mode A plan template and Mode C orchestration live in companion files. |
| `workflow-extend` | "/swe-workbench:extend", "extend the PR", "add this on top of the current PR", mid-PR follow-on, related sub-idea on the in-flight branch. | Captures a sub-idea inline (no new top-level issue), implements it on the same branch as the existing PR, skipping Phase 1 (Branch). Preserves Phases 2–5: Implement via TDD, Verify via `superpowers:verification-before-completion`, Review via `superpowers:code-reviewer` + `swe-workbench:reviewer` (with scope-creep guard), Deliver via `swe-workbench:workflow-commit-and-pr` "Update existing PR" path. |
| `workflow-cleanup-merged` | "clean up merged branch", "remove worktree", "delete branch after merge", after a PR is merged. | Verifies merge via `gh pr view` (squash-merge safe). When rimba is available, uses `rimba remove <task>` for worktree teardown (dirty/unpushed checks included) and recommends `rimba hook install` for future automation. Without rimba, runs the `git worktree list --porcelain` safety-check path. Branch deletion and main-sync are always handled in-skill. Invoked by `/swe-workbench:cleanup-merged` and by Mode C orchestration Step 7. |
| `workflow-worktree-session` | "in a worktree", "open the X worktree", "move into worktree", "switch to worktree", "enter worktree", "exit the worktree", "leave worktree". | Routes to `EnterWorktree(path=…)` for existing worktrees; defers to `superpowers:using-git-worktrees` for new ones (that skill handles consent, baseline tests, and calls `EnterWorktree` itself). `ExitWorktree(action: "keep"\|"remove")` on the way out. Forbids `Bash(cd …)` as a session-switch mechanism. |

This skill is an orchestrator — it coordinates other skills rather than restating their content.

### Integrations — auto-load on ticket references

| Skill | Triggers | Delegation model |
|---|---|---|
| `ticket-context` | Jira keys (`[A-Z]+-\d+`), `atlassian.net/browse/...`, Confluence wiki URLs, `github.com/.../(issues\|pull)/N`, `#N` refs. | Invoked by command bodies as a prelude before subagent delegation. Fetches via `mcp__atlassian__*` and `gh` CLI. Returns structured context (title, summary, acceptance criteria, linked refs, recent comments). Does not act on the ticket — only resolves it. |

