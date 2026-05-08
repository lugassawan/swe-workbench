# Skill catalog

All `swe-workbench` skills available in this plugin. Use the `Skill` tool to invoke any of these.

## Principles

- `swe-workbench:principle-api-design` — API design: contract-first, versioning, idempotency, REST/RPC/event trade-offs.
- `swe-workbench:principle-clean-architecture` — Clean Architecture: dependency rule, ports and adapters, domain-centric layering.
- `swe-workbench:principle-clean-code` — Clean code: DRY, KISS, YAGNI, naming, function length, abstraction level.
- `swe-workbench:principle-concurrency` — Concurrency: race conditions, deadlock, structured concurrency, cancellation, backpressure.
- `swe-workbench:principle-ddd` — Domain-Driven Design: bounded contexts, aggregates, ubiquitous language, domain events.
- `swe-workbench:principle-design-patterns` — Design patterns: GoF catalog — Strategy, Factory, Observer, Decorator, Adapter, and more.
- `swe-workbench:principle-error-handling` — Error handling: errors as values, classification, wrapping, retry, circuit breakers.
- `swe-workbench:principle-observability` — Observability: logs vs metrics vs traces, structured logging, OpenTelemetry, SLI/SLO.
- `swe-workbench:principle-performance` — Performance: latency vs throughput, profile-before-optimize, Big-O, allocation pressure, data locality, N+1 queries.
- `swe-workbench:principle-security` — Security: trust boundaries, input validation, secrets handling, secure defaults, threat modeling.
- `swe-workbench:principle-solid` — SOLID principles: SRP, OCP, LSP, ISP, DIP — responsibility, coupling, abstractions.
- `swe-workbench:principle-tdd` — TDD: red-green-refactor, test-first, F.I.R.S.T., Arrange-Act-Assert.

## Languages

- `swe-workbench:language-go` — Go idioms: error handling, goroutines, channels, interfaces, context, standard library.
- `swe-workbench:language-java` — Java idioms: records, sealed types, virtual threads, streams, JDK 21+ patterns.
- `swe-workbench:language-kotlin` — Kotlin idioms: null safety, coroutines, sealed interfaces, scope functions, Flow.
- `swe-workbench:language-python` — Python idioms: PEP 8, type hints, dataclasses, asyncio, generators, pytest.
- `swe-workbench:language-rust` — Rust idioms: ownership, borrowing, lifetimes, traits, iterators, error handling.
- `swe-workbench:language-swift` — Swift idioms: optionals, value types, actors, async/await, protocols, Result builders.
- `swe-workbench:language-typescript` — TypeScript/JavaScript idioms: strict mode, discriminated unions, async patterns, Node.

## Workflows

- `swe-workbench:workflow-bug-triage` — Investigate-and-file-issue counterpart to /debug. Iron Law (no fix without root cause), 4-phase loop, files structured issue with code-path table and impact assessment.
- `swe-workbench:workflow-cleanup-merged` — Post-merge cleanup: fast-forward main, then remove worktree (via `rimba remove` if available, else `git worktree` shell path), delete local + remote branch.
- `swe-workbench:workflow-commit-and-pr` — Pre-merge half: enforces [type] commit format, branch-naming, [no ci] for docs, draft/ready prompt, PR template detection, and post-create /review CTA.
- `swe-workbench:workflow-development` — Full development lifecycle: Branch → Implement → Verify → Review → Deliver. Phase 1 uses `rimba add` when rimba is available; falls back to `superpowers:using-git-worktrees`.
- `swe-workbench:workflow-pr-review` — Remote-PR review orchestration: ephemeral worktree + reviewer agent + GraphQL thread dedup + REST inline-comment post + APPROVE/COMMENT submit. Invoked by `/review` PR mode.
- `swe-workbench:workflow-worktree-session` — Start, switch, or end a worktree-bound session via `EnterWorktree` / `ExitWorktree`. No claude restart.

## Other

- `swe-workbench:ticket-context` — Fetch structured context from Jira, Confluence, and GitHub issues/PRs before starting work.
