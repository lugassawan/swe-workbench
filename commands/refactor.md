---
description: Invoke the refactorer subagent for a behavior-preserving refactor
argument-hint: <file, function, or module>
---

Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference (Jira key like `PROJ-123`, an `atlassian.net` URL, a Confluence wiki URL, or a GitHub issue/PR URL or `#NNN`), invoke the `swe-workbench:ticket-context` skill first; a refactor motivated by a ticket needs the ticket's scope and constraints in the delegation context.

Delegate to the `refactorer` subagent. Its output must include:

1. **Diagnosis** — which smell is present (Long Method, Feature Envy, Primitive Obsession, Shotgun Surgery, Divergent Change, etc.) and why it hurts.
2. **Target state** — the shape of the code after refactoring, referenced to Fowler's catalog.
3. **Step plan** — ordered steps, each behavior-preserving and independently testable, each named from the catalog (Extract Function, Move Function, Replace Conditional with Polymorphism, Introduce Parameter Object…).
4. **Verification** — which tests protect each step; write characterization tests first if coverage is missing.

Absolute rule: no feature changes during refactoring.
