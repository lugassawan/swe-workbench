---
name: principle-clean-code
description: Clean code, DRY, KISS, YAGNI, function length, naming, abstraction level, error handling. Auto-load when writing functions, naming variables, reviewing code clarity, discussing comments, or debating whether to abstract.
---

# Clean Code

## Function Rules

| Rule | Guideline |
|------|-----------|
| **Function length** | Prefer under 20 lines. Extract when doing two things. |
| **Naming** | Name reveals intent. No abbreviations except universal ones (ctx, err, id). |
| **Abstraction level** | One level per function. Don't mix SQL strings with business logic. |
| **Comments** | Explain WHY, not WHAT. If code needs WHAT comments, rename or extract. |
| **Error handling** | Handle at the appropriate layer. Don't swallow errors silently. |

## DRY — Rule of Three

Don't abstract on first duplication. Extract on the third occurrence. Two is coincidence; three is pattern.

## KISS

Choose the simplest solution that satisfies requirements. If you're building a framework to solve a feature, step back.

## YAGNI

Don't build for hypothetical future requirements. Design for what exists today.

## YAGNI does NOT override DIP for testability

Interfaces for cross-layer dependencies are a **present need**, not speculation:
- Tests exist now; mocking requires abstractions now.
- "Too small for interfaces" is never valid when the dependency crosses an architectural boundary.
- If a component talks to a database, HTTP API, or external service, it gets an interface — period.

The second caller is not required. The boundary is.

## When these hurt

- Scripts and one-off jobs where indirection costs more than it saves.
- Pure algorithmic code where the shape of the computation matters more than the shape of the objects.
- Throwaway prototypes (but only if you mean it — prototypes that ship become production code).
