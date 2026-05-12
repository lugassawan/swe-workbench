# Skill catalog

All `swe-workbench` skills available in this plugin. Use the `Skill` tool to invoke any of these.

## Principles

- `swe-workbench:principle-accessibility` — Accessibility: WCAG 2.2 AA, semantic HTML, ARIA, keyboard navigation, focus management, color contrast, screen-reader compatibility.
- `swe-workbench:principle-api-design` — API design: contract-first, versioning, idempotency, REST/RPC/event trade-offs.
- `swe-workbench:principle-clean-architecture` — Clean Architecture: dependency rule, ports and adapters, domain-centric layering.
- `swe-workbench:principle-clean-code` — Clean code: DRY, KISS, YAGNI, naming, function length, abstraction level.
- `swe-workbench:principle-code-review` — Code review: four-axis lens (correctness, security, design, tests), confidence-based filtering, comment tone, nitpick filtering.
- `swe-workbench:principle-concurrency` — Concurrency: race conditions, deadlock, structured concurrency, cancellation, backpressure.
- `swe-workbench:principle-cost-awareness` — Cost awareness: FinOps mindset, egress, right-sizing, scale-to-zero, cost-per-request, storage tiers, observability cost.
- `swe-workbench:principle-data-modeling` — Data modeling: storage paradigm selection, normalization depth, indexing strategy, hot-key avoidance, schema evolution, query-first design, retention.
- `swe-workbench:principle-ddd` — Domain-Driven Design: bounded contexts, aggregates, ubiquitous language, domain events.
- `swe-workbench:principle-design-patterns` — Design patterns: GoF catalog — Strategy, Factory, Observer, Decorator, Adapter, and more.
- `swe-workbench:principle-distributed-systems` — Distributed systems: CAP/PACELC, consistency models, consensus, quorum, logical clocks, replication, delivery semantics.
- `swe-workbench:principle-error-handling` — Error handling: errors as values, classification, wrapping, retry, circuit breakers.
- `swe-workbench:principle-event-driven` — Event-driven architecture: event sourcing, CQRS, sagas, schema evolution, consumer groups, DLQ, idempotent handlers.
- `swe-workbench:principle-i18n` — Internationalization & localization: locale-aware formatting, time zones, plural rules, message catalogs, RTL layout, ISO 8601, currency.
- `swe-workbench:principle-observability` — Observability: logs vs metrics vs traces, structured logging, OpenTelemetry, SLI/SLO.
- `swe-workbench:principle-performance` — Performance: latency vs throughput, profile-before-optimize, Big-O, allocation pressure, data locality, N+1 queries.
- `swe-workbench:principle-refactoring` — Refactoring discipline: Fowler's catalog, smell→move mapping, rule of three, characterization-tests-first, small behavior-preserving steps with green between.
- `swe-workbench:principle-resiliency` — Resiliency: failure domains, bulkheads, graceful degradation, fail-fast vs fail-soft, health checks, blast radius containment.
- `swe-workbench:principle-security` — Security: trust boundaries, input validation, secrets handling, secure defaults, threat modeling.
- `swe-workbench:principle-solid` — SOLID principles: SRP, OCP, LSP, ISP, DIP — responsibility, coupling, abstractions.
- `swe-workbench:principle-tdd` — TDD: red-green-refactor, test-first, F.I.R.S.T., Arrange-Act-Assert.
- `swe-workbench:principle-testing` — Testing strategy: test pyramid, doubles taxonomy, coverage-vs-confidence, mutation testing, flaky-test triage, contract testing, fixtures and builders, property-based tests.
- `swe-workbench:principle-version-control` — Version control: atomic commits, commit-message quality, branching strategy, rebase vs merge, squash vs preserve, PR description quality.

## Languages

- `swe-workbench:language-bash` — Bash idioms: strict mode, quoting, parameter expansion, arrays, pipefail, trap cleanup, idempotency, heredocs, and POSIX portability.
- `swe-workbench:language-go` — Go idioms: error handling, goroutines, channels, interfaces, context, standard library.
- `swe-workbench:language-java` — Java idioms: records, sealed types, virtual threads, streams, JDK 21+ patterns.
- `swe-workbench:language-kotlin` — Kotlin idioms: null safety, coroutines, sealed interfaces, scope functions, Flow.
- `swe-workbench:language-python` — Python idioms: PEP 8, type hints, dataclasses, asyncio, generators, pytest.
- `swe-workbench:language-rust` — Rust idioms: ownership, borrowing, lifetimes, traits, iterators, error handling.
- `swe-workbench:language-swift` — Swift idioms: optionals, value types, actors, async/await, protocols, Result builders.
- `swe-workbench:language-typescript` — TypeScript/JavaScript idioms: strict mode, discriminated unions, async patterns, Node.

## Workflows

- `swe-workbench:workflow-bug-triage` — Investigate-and-file-issue counterpart to /debug. Iron Law (no fix without root cause), 4-phase loop, files structured issue with code-path table and impact assessment.
- `swe-workbench:workflow-cleanup-merged` — Post-merge cleanup: fast-forward main (which auto-cleans via rimba post-merge hook when active), then verify; falls back to `rimba remove` or `git worktree` shell path; deletes local + remote branch.
- `swe-workbench:workflow-codebase-audit` — Cold-start, time-boxed, multi-axis audit sweep with ranked findings, reasoning chains, and counter-evidence calibration.
- `swe-workbench:workflow-commit-and-pr` — Pre-merge half: enforces [type] commit format, branch-naming, [no ci] for docs, draft/ready prompt, PR template detection, and post-create /review CTA.
- `swe-workbench:workflow-development` — Full development lifecycle: Branch → Implement → Verify → Review → Deliver. Phase 1 uses `rimba add` when rimba is available; falls back to `superpowers:using-git-worktrees`.
- `swe-workbench:workflow-pr-review` — Remote-PR review orchestration: ephemeral worktree + reviewer agent + GraphQL thread dedup + REST inline-comment post + APPROVE/COMMENT submit. Invoked by `/review` PR mode.
- `swe-workbench:workflow-worktree-session` — Start, switch, or end a worktree-bound session via `EnterWorktree` / `ExitWorktree`. No claude restart.

## Other

- `swe-workbench:ticket-context` — Fetch structured context from Jira, Confluence, and GitHub issues/PRs before starting work.
