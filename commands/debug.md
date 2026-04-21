---
description: Invoke the debugger subagent to diagnose a bug, failing test, or unexpected behavior — root-cause first, then a minimal, principle-aware fix with a regression test
argument-hint: <symptom, failing test, or error, optionally with a ticket ref>
---

Symptom: $ARGUMENTS

If $ARGUMENTS contains a ticket reference (Jira key like `PROJ-123`, an `atlassian.net` URL, a Confluence wiki URL, or a GitHub issue/PR URL or `#NNN`), invoke the `swe-workbench:ticket-context` skill first and prepend its structured summary to the delegation context below.

Delegate to the `debugger` subagent. Its output must include:

1. **Repro** — exact steps, inputs, and the observed failure (command, stack trace, or assertion delta).
2. **Hypotheses** — 2–3 candidate causes, each falsifiable with the observation that would confirm or rule it out.
3. **Root cause** — the single cause supported by concrete evidence (log line, stack frame, state diff). No speculation.
4. **Minimal fix** — smallest behavior-changing patch that resolves the root cause; call out what it deliberately does NOT touch.
5. **Regression test** — the test that fails before the fix and passes after. Name it and its location.
6. **SOLID / Clean-Arch risks** — whether the bug's shape signals a principle violation, and whether the minimal fix papers over it.

Absolute rule: no fix without a failing test first. This command changes behavior to match spec — it is not a refactor.
