# Principle catalog

All `swe-workbench` principle rules. These are plain `.md` files under `rules/`, not skills — load one on demand with `cat "$CLAUDE_PLUGIN_ROOT/rules/<name>.md"` when it applies.

- `principle-accessibility` — Accessibility: WCAG 2.2 AA, semantic HTML, ARIA, keyboard navigation, focus management, color contrast, screen-reader compatibility. → `rules/principle-accessibility.md`
- `principle-api-design` — API design: contract-first, versioning, idempotency, REST/RPC/event trade-offs. → `rules/principle-api-design.md`
- `principle-clean-architecture` — Clean Architecture: dependency rule, ports and adapters, domain-centric layering. → `rules/principle-clean-architecture.md`
- `principle-clean-code` — Clean code: DRY, KISS, YAGNI, naming, function length, abstraction level. → `rules/principle-clean-code.md`
- `principle-code-review` — Code review: five-axis lens (correctness, security, design, tests, comment quality), confidence-based filtering, comment tone, nitpick filtering. → `rules/principle-code-review.md`
- `principle-communication` — Communication & output discipline: terse "caveman" output mode (lite/full/ultra), drop filler/hedging, preserve code symbols and error strings verbatim, auto-clarity carve-out. → `rules/principle-communication.md`
- `principle-concurrency` — Concurrency: race conditions, deadlock, structured concurrency, cancellation, backpressure. → `rules/principle-concurrency.md`
- `principle-cost-awareness` — Cost awareness: FinOps mindset, egress, right-sizing, scale-to-zero, cost-per-request, storage tiers, observability cost. → `rules/principle-cost-awareness.md`
- `principle-data-modeling` — Data modeling: storage paradigm selection, normalization depth, indexing strategy, hot-key avoidance, schema evolution, query-first design, retention. → `rules/principle-data-modeling.md`
- `principle-ddd` — Domain-Driven Design: bounded contexts, aggregates, ubiquitous language, domain events. → `rules/principle-ddd.md`
- `principle-design-patterns` — Design patterns: GoF catalog — Strategy, Factory, Observer, Decorator, Adapter, and more. → `rules/principle-design-patterns.md`
- `principle-distributed-systems` — Distributed systems: CAP/PACELC, consistency models, consensus, quorum, logical clocks, replication, delivery semantics. → `rules/principle-distributed-systems.md`
- `principle-error-handling` — Error handling: errors as values, classification, wrapping, retry, circuit breakers. → `rules/principle-error-handling.md`
- `principle-event-driven` — Event-driven architecture: event sourcing, CQRS, sagas, schema evolution, consumer groups, DLQ, idempotent handlers. → `rules/principle-event-driven.md`
- `principle-i18n` — Internationalization & localization: locale-aware formatting, time zones, plural rules, message catalogs, RTL layout, ISO 8601, currency. → `rules/principle-i18n.md`
- `principle-observability` — Observability: logs vs metrics vs traces, structured logging, OpenTelemetry, SLI/SLO. → `rules/principle-observability.md`
- `principle-performance` — Performance: latency vs throughput, profile-before-optimize, Big-O, allocation pressure, data locality, N+1 queries. → `rules/principle-performance.md`
- `principle-postmortem` — Postmortem principles: blameless culture, root cause analysis (5 Whys, Fishbone/Ishikawa), incident document structure, action-item discipline, MTTD/MTTR metrics. → `rules/principle-postmortem.md`
- `principle-refactoring` — Refactoring discipline: Fowler's catalog, smell→move mapping, rule of three, characterization-tests-first, small behavior-preserving steps with green between. → `rules/principle-refactoring.md`
- `principle-release-engineering` — Release engineering: semver discipline, expand-contract for breaking changes, idempotent release automation, post-release verification, rollback planning, release-notes audience. → `rules/principle-release-engineering.md`
- `principle-resiliency` — Resiliency: failure domains, bulkheads, graceful degradation, fail-fast vs fail-soft, health checks, blast radius containment, idempotency keys, safe retry, rate limiting, token bucket, backpressure, jitter. → `rules/principle-resiliency.md`
- `principle-security` — Security: trust boundaries, input validation, secrets handling, secure defaults, threat modeling. → `rules/principle-security.md`
- `principle-solid` — SOLID principles: SRP, OCP, LSP, ISP, DIP — responsibility, coupling, abstractions. → `rules/principle-solid.md`
- `principle-tdd` — TDD: red-green-refactor, test-first, F.I.R.S.T., Arrange-Act-Assert. → `rules/principle-tdd.md`
- `principle-testing` — Testing strategy: test pyramid, doubles taxonomy, coverage-vs-confidence, mutation testing, flaky-test triage, contract testing, fixtures and builders, property-based tests. → `rules/principle-testing.md`
- `principle-version-control` — Version control: atomic commits, commit-message quality, branching strategy, rebase vs merge, squash vs preserve, PR description quality. → `rules/principle-version-control.md`
- `principle-product-design` — UX and product design: Nielsen's 10 usability heuristics, visual hierarchy, information architecture, interaction design patterns, design-system compliance, responsive design (Accessibility/WCAG is a separate rule, `rules/principle-accessibility.md`). → `rules/principle-product-design.md`
