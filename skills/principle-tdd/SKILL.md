---
name: principle-tdd
description: Test-Driven Development (TDD) — red-green-refactor, test-first, spec first, Arrange-Act-Assert, F.I.R.S.T. principles; writing tests before code; making tests fast and isolated; test doubles (mock, stub, fake, spy), mocking-as-design-feedback, outside-in vs inside-out TDD. Auto-load when implementing a feature TDD-style, fixing a bug with tests, discussing test strategy, reviewing test quality, or writing the test before the implementation.
---

# Test-Driven Development

## The loop
1. **Red** — one failing test describing the next slice of behavior. Run it; confirm it fails for the right reason.
2. **Green** — simplest production code that passes. Hard-coding is allowed — it will be driven out by the next test.
3. **Refactor** — with all tests green, improve the code and the tests. Never refactor on red.

Each cycle is minutes, not hours.

## Rule of three
Duplication triggers refactor on the third occurrence. Two is coincidence; three is pattern.

## F.I.R.S.T.
- **Fast** — milliseconds.
- **Isolated** — independent of order and other tests.
- **Repeatable** — deterministic anywhere.
- **Self-validating** — automatic pass/fail.
- **Timely** — written just before the production code.

## What counts as "refactor"
*Structural improvement with all tests green — no new behavior.*
- **Rename, extract, move** — anything that clarifies intent or repositions code to the layer that owns it.
- **Never add behavior during refactor** — if a test turns red mid-refactor, revert the last step; the cycle was too large.
- **Tests are part of refactor too** — clean up names, builders, and assertions when production code changes shape.

## Test doubles — pick the cheapest that works
*One double per behavioral boundary, not one double per collaborator.*
- **Fake** — working implementation (in-memory DB) — best for fast integration without real infrastructure.
- **Stub** — canned response — isolates the path under test.
- **Spy** — records calls for post-hoc assertion.
- **Mock** — pre-programmed expectations; fails on unexpected calls — strictest, most brittle.

Use the cheapest double that still proves the behavior.

## Mocking pain is design feedback
*A mock that is hard to build signals a bad seam, not a bad mock.*
- **Deep chains** (`a.b().c().d()`) — the SUT reaches too far; introduce a collaborator interface at the inflection point.
- **Leaky internals** — mocking private state means the test knows the implementation; test through the public API instead.
- **Time or network coupling** — inject a `Clock` or `HttpClient` abstraction; never mock the system clock globally.
- **Growing setup** — more than ~5 lines to configure a double signals too many responsibilities in the SUT.

## Outside-in vs inside-out
*Pick by which end has more unknowns.*
- **Outside-in** — start with an acceptance test; let it fail; discover collaborators via mocks; fill in implementations inward. Best for discovering internal collaborators when the integration boundary is known.
- **Inside-out** — start at the domain core; build units independently; compose outward. Best when domain logic is rich and invariant-heavy, regardless of interface stability.

## What to test
- **Behavior**, not implementation. "Returns total with tax" survives refactor; "calls foo then bar" does not.
- **Boundaries** — empty, single, max, null, unicode.
- **Error paths** — wrong-currency transfer, expired token, upstream 500.

## What NOT to test
- Getters/setters with no logic.
- Framework code you don't own.
- Private methods directly — test through the public API.

## When TDD helps most
- Logic-heavy domain code.
- Bug fixes — write a reproducing test before fixing.
- Refactoring — characterization tests first.

## When TDD is friction
- Exploratory spikes with unknown design — spike, throw away, then TDD the real thing.
- Pure UI tweaks where visual inspection is the oracle.
- Trivial plumbing fully covered by a higher-level integration test.

## Red Flags — stop and reassess

| Flag | Problem |
|------|---------|
| Tests mirror the implementation | Implementation-coupled assertions or over-mocking; refactors break tests without catching bugs |
| Tests share mutable state | Fail randomly in parallel; order-dependent — always isolate |
| Giant arrange blocks | What's under test is hidden; extract test-data builders |
| "I'll add tests later" | Test-after yields a fraction of TDD's design benefit; rarely happens |
| Refactoring while a test is red | New behavior smuggled in; revert and re-run the micro-cycle |
| Flaky on parallel runs | Shared global state or time dependency; inject a `Clock` or isolate state |
