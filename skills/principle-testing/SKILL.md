---
name: principle-testing
description: Testing strategy and architecture — test pyramid (unit / integration / e2e), test doubles taxonomy (stub / mock / spy / fake), coverage-vs-confidence, mutation testing, flaky-test triage, contract testing, property-based and characterization tests, fixtures and test data builders. Distinct from principle-tdd which covers the red-green-refactor micro-cycle. Auto-load when discussing test strategy, mock vs real dependency, coverage adequacy, test pyramid balance, flaky test diagnosis, contract testing, or test architecture.
---

# Testing Strategy and Architecture

Strategy and architecture, not the red-green-refactor discipline. For that, see `principle-tdd`.

## The pyramid

Three tiers, wide base up: **unit → integration → e2e**. Baseline ratio: ~70% unit, ~20% integration, ~10% e2e — adjust toward more integration for infrastructure-heavy systems, more e2e for UI-heavy products.

Inverting the pyramid (heavy e2e, thin unit) produces a slow, brittle suite — e2e tests amplify flakiness and punish every external dependency.

- **Unit** — one class or function, no I/O, milliseconds.
- **Integration** — two or more collaborators, real infrastructure (DB, message bus), seconds.
- **e2e** — full stack through the UI or API gateway; minutes.

Prefer more granular tests. One integration test that exercises a migration is worth more than five e2e tests covering the same path.

## Test doubles

Five kinds (Meszaros's xUnit Patterns taxonomy). State-based: Stub, Fake. Behavior-verification: Spy, Mock. Dummy is a degenerate no-op.

| Double | What it does | When to use |
|--------|-------------|-------------|
| Dummy | Passed but never called | Satisfying required params |
| Stub | Returns canned responses | Isolating the path under test |
| Fake | Working implementation (e.g. in-memory DB) | Fast integration tests |
| Spy | Records calls for post-hoc assertion | Verifying interactions |
| Mock | Pre-programmed expectations; fails on violation | Strict boundary contracts |

**Mock only at trust boundaries**: network, clock, filesystem, random, external services. The seam is domain ↔ infrastructure (Clean Architecture's dependency rule). Everything inside the domain is instantiated for real.

If a collaborator is hard to instantiate, that is a design signal — recommend a refactor, not a mock.

## Coverage vs confidence

Line coverage is a metric, not a quality signal. 90% coverage with assertions only on getters is worthless; 60% coverage with well-targeted branch assertions is not.

**Mutation testing** measures kill rate — surviving mutants reveal assertions that don't bind to observable behavior. Tools: Stryker (JS/TS), mutmut (Python), cargo-mutants (Rust), PIT (Java).

Aim to kill 80%+ mutants in business-critical paths. Don't chase line count; chase surviving mutants.

## Flaky tests

Three root causes:

1. **Shared mutable state** — tests leave rows, cache entries, or global flags for later tests.
2. **Time / order dependence** — assertions on wall clock, ordering assumptions, race conditions.
3. **Undeclared external dependency** — network calls, filesystem paths, env vars not controlled.

Quarantine without root-cause is debt. A `@retry` annotation hides the diagnosis. Fix the cause; delete the annotation.

## Contract testing

Consumer-driven contracts let a consumer codify the shape of the responses it needs; the provider verifies it on every build. Tools: Pact, Spring Cloud Contract. Pact supports both HTTP and message (async/event-driven) contracts — the latter matters when services communicate via queues or event buses.

When to use: microservices where a fast unit suite still leaves an integration crater. Not a substitute for integration tests — a complement that shifts verification left.

## Fixtures and builders

Magic values defeat readability. A fluent builder makes intent explicit:

- `createUser(30, "active")` — what does 30 mean?
- `UserBuilder().with_age(30).with_status("active").build()` — obvious.

One builder per aggregate root. Keep factories close to tests, not scattered across setUp methods.

## Property-based and characterization tests

**Property-based** — generate hundreds of inputs and assert invariants hold for all. Finds edge cases example-based tests miss. Tools: Hypothesis (Python), fast-check (JS), proptest (Rust), jqwik (Java).

**Characterization tests** — lock in existing behavior of legacy code before refactoring. Write them first; use them as a safety net.

## When testing hurts

- One-off scripts and CLI wrappers — integration cost exceeds value.
- Exploratory spikes — spike, discard, then TDD the real thing.
- Testing the framework rather than your use of it (asserting that `express()` routes middleware).
- Prototypes you're prepared to throw away.

## Common Excuses — and Why They're Wrong

| Excuse | Reality |
|--------|---------|
| "90% coverage means we're well tested" | Coverage measures execution, not correctness. Surviving mutants reveal the gaps coverage hides. |
| "Mocking the DB is faster to write" | A mock proves the code compiles, not that it works with a real store. Use a fake or a real DB. |
| "e2e tests prove the system works end-to-end" | They prove the happy path when green. They obscure which layer failed when red. |
| "This flaky test is just CI noise" | Noise is a symptom. The root cause is untested state or an undeclared dependency. |

## Red Flags — Stop and Reassess

- Mock-heavy unit suite with zero integration tests — no evidence the parts work together.
- Tests that bind to private methods or internal call sequences.
- 90%+ line coverage with production bugs that slipped through critical paths.
- `@retry` / `--flaky` annotations with no linked root-cause ticket.
- Contract changes caught only in staging or production.
- Test setup longer than the test itself — extract builders.

## If You Catch Yourself Thinking…

| Thought | What to Do Instead |
|---------|-------------------|
| "I'll just mock the whole database" | Use a fake (in-memory) or a real DB in a container. Mocks prove nothing about SQL. |
| "Retry will fix the flakiness" | Quarantine to a separate CI job and open a ticket. Then fix the root cause. Retries and skips both hide the bug. |
| "More e2e tests = more confidence" | Invert: more integration tests = faster feedback. Reserve e2e for critical user journeys. |
| "We have great coverage, we're safe" | Run mutation tests on the critical path. Kill rate tells the truth. |
