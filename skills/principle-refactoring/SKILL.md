---
name: principle-refactoring
description: Refactoring discipline — Fowler's catalog of behavior-preserving moves (Extract Function, Inline Variable, Move Function, Replace Conditional with Polymorphism, Introduce Parameter Object, Extract Class), the smell→move mapping (Long Method, Large Class, Feature Envy, Data Clumps, Primitive Obsession, Shotgun Surgery, Divergent Change, Speculative Generality), the rule of three, characterization-tests-before-touching-legacy, and small-steps-with-green-between discipline. Distinct from principle-clean-code (naming/length aesthetics) and principle-design-patterns (GoF catalog selection). Auto-load when discussing refactoring strategy, code smells, when to extract, characterization tests for legacy code, or behavior-preserving structural change.
---

# Refactoring Discipline

Structural change without behavior change. For the GoF pattern catalog, see `principle-design-patterns`. For naming and function-length aesthetics, see `principle-clean-code`.

## The discipline

Four non-negotiable rules:

- **Every step preserves behavior.** Tests must pass before and after each step.
- **No feature changes during refactoring.** Find a bug? Note it — fix it in a separate commit.
- **Small steps.** Each step is independently reviewable and revertable.
- **Green between steps.** Run tests after each move. If red, revert immediately.

## Smells → moves

| Smell | Triggering move(s) |
|---|---|
| Long Method | Extract Function, Decompose Conditional, Replace Temp with Query — *Quality stage (`workflow-development`) gives the objective trigger via cyclomatic / cognitive complexity thresholds* |
| Large Class | Extract Class, Extract Interface, Move Function — *Quality stage (`workflow-development`) gives the objective trigger via file / class length* |
| Feature Envy | Move Function, Move Field |
| Data Clumps | Introduce Parameter Object, Extract Class |
| Primitive Obsession | Replace Primitive with Object, Introduce Parameter Object |
| Shotgun Surgery | Move Function, Move Field, Inline Function |
| Divergent Change | Extract Class (split responsibilities) |
| Speculative Generality | Inline Function, Collapse Hierarchy, Remove Middle Man |

## Fowler's catalog (key moves)

- **Extract Function** — when a block of code has a name that explains what it does; extract it.
- **Inline Function** — when the body is as clear as the function name; remove the indirection.
- **Inline Variable** — when the temp name adds no clarity over the expression itself; remove the indirection.
- **Extract Variable** — when an expression needs explanation; name it.
- **Rename Variable/Function** — when the current name no longer matches intent.
- **Move Function** — when a function references more of another module's data than its own.
- **Extract Class** — when a class carries two clusters of behavior with distinct change reasons.
- **Introduce Parameter Object** — when a group of parameters always appears together.
- **Replace Conditional with Polymorphism** — when a switch/if dispatches on type; move to subclass/strategy.
- **Replace Temp with Query** — when a temp variable stores a computable result; extract a function.
- **Decompose Conditional** — when complex conditions obscure intent; extract condition and branches.

## Rule of three

Two similar instances tolerate duplication; a third triggers extraction — see `principle-clean-code` for the full DRY rationale. Guard against premature abstraction: one caller does not justify a shared helper.

## Characterization tests first

Before touching legacy code with no test coverage, write characterization tests that lock in current behavior — even if the behavior is wrong. These tests become your safety net; they should pass before and after every refactoring step. For the technique in full, see `principle-testing`.

## When refactoring is overkill

- Throw-away spike code or proof-of-concept scripts — ship the signal, discard the code.
- Code that is about to be deleted — refactoring dead code adds zero value.
- Refactoring without a forcing function — no current pain, no near-term feature depending on this code.
- A codebase with no test coverage and no willingness to write characterization tests — the safety net is absent.

## Red Flags — Stop and Reassess

| Flag | Why it matters |
|---|---|
| Refactor PR also adds a feature | Mixed intent; the "behavior-preserving" guarantee is unverifiable. |
| Tests changed to make the refactor pass | You changed behavior; this is a fix, not a refactor. |
| "While I'm here" rewrites | Scope creep. Note it, defer to a dedicated refactor ticket. |
| Refactoring without a green test suite | No safety net — every step is a gamble. Write characterization tests first. |
| Step size grows to match the IDE's "safe refactor" | IDEs miss dynamic dispatch, reflection, and cross-module side effects. Keep steps small. |
