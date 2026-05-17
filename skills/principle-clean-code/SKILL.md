---
name: principle-clean-code
description: Clean code, DRY, KISS, YAGNI, function length, naming, abstraction level, error handling, function argument count, Command-Query Separation, Boy Scout Rule, intent-revealing naming. Auto-load when writing functions, naming variables, reviewing code clarity, discussing comments, or debating whether to abstract.
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
| **Argument count** | 0 is ideal; 1 is common; 2 is acceptable; 3+ is suspicious. A boolean flag argument is a hidden second function — split it. |
| **Command-Query Separation** | A function either changes state or returns a value — not both. |

## Naming reveals intent
*Names are documentation that can't go stale.*
- **Intent over implementation** — `calculateShippingCost` not `processData`; `isEligibleForDiscount` not `check`.
- **No Hungarian or type encodings** — `strName`, `iCount`, `bActive` encode the type, not the meaning; the compiler already knows the type.
- **Searchable names beat short names** — `MAX_RETRY_ATTEMPTS` is greppable; `n` is not. Single-letter names only in short loop counters where scope fits a screen.
- **One word per concept in a module** — `fetch`, `retrieve`, and `get` create false distinctions; pick one and apply it consistently.
- **Positive booleans** — `isActive`, `hasExpired`, `canDelete`; negated names (`isNotLoaded`, `notActive`) invert reader expectations and compose poorly.

## DRY — Rule of Three

Don't abstract on first duplication. Extract on the third occurrence. Two is coincidence; three is pattern.

*Duplication detectors (`jscpd`, `dupl`, `mvn pmd:cpd-check`) give an objective signal — see the Quality stage in `workflow-development`.*

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

## Boy Scout Rule — scope-bounded
*Leave the code slightly better than you found it — within the diff under review.*
- **Fair game** — rename a poorly named variable, extract a multi-line condition, remove a dead comment — inside files already touched by the PR.
- **Not fair game** — repo-wide renames or refactors triggered by noticing unrelated code; those belong in a dedicated `principle-refactoring` session.
- **Compound improvements compound reviews** — unbounded cleanup in a feature branch obscures intent and inflates diff size.
- **Commit granularity** — if the cleanup is significant, isolate it in a separate commit so reviewers can approve or skip it independently.

## When these hurt

- Scripts and one-off jobs where indirection costs more than it saves.
- Pure algorithmic code where the shape of the computation matters more than the shape of the objects.
- Throwaway prototypes (but only if you mean it — prototypes that ship become production code).
- Hot paths where layering adds call-stack overhead that matters — profile first, then flatten deliberately.
- Generated code and legacy code under characterization tests — stabilize behavior before applying clean-code conventions.

## Red Flags

| Flag | Problem |
|------|---------|
| 3+ arguments without a parameter object | Callers must remember order; test setup grows with every new param |
| Function returns a value AND mutates state | Violates CQS; callers can't compose calls safely or predict side effects |
| Hungarian or type prefixes (`strName`, `bActive`) | Type is already in the signature; name encodes noise, not intent |
| Comment explains WHAT instead of WHY | Name the thing better; delete the comment |
| Same literal in 3+ sites with no name | Rule of three — extract to a named constant |
| Function name is a vague verb (`process`, `handle`, `manage`) | Reader can't predict behavior; use precise verbs that describe what changes or returns |
