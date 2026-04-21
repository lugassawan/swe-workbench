---
name: principle-tdd
description: Test-Driven Development — red, green, refactor; writing tests first; making tests fast and isolated. Auto-load when implementing a feature, fixing a bug with tests, discussing test strategy, or reviewing test quality.
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

## Common failure modes
- Tests that mirror the implementation (over-mocking).
- Tests sharing mutable state and failing in parallel.
- Giant setups hiding what's under test — extract test data builders.
- "I'll add tests later." You won't.
