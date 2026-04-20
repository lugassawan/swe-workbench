---
description: Run a strict red-green-refactor loop for a feature
argument-hint: <feature description>
---

Feature: $ARGUMENTS

Run a disciplined TDD loop.

1. **Red** — write ONE failing test that describes the next slice of behavior. Run it and confirm it fails for the expected reason.
2. **Green** — write the minimum production code to pass that test. No speculative code, no extra features.
3. **Refactor** — only with all tests green, improve structure (rename, extract, dedupe). Re-run tests after each change.
4. Repeat until the feature is complete.

Hard rules:
- No production code without a failing test driving it.
- Never refactor on red.
- Tests must be fast, isolated, repeatable, self-validating, timely (F.I.R.S.T.).

Surface every step explicitly: `RED: …`, `GREEN: …`, `REFACTOR: …`.
