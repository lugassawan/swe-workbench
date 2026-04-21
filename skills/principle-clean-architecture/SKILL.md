---
name: principle-clean-architecture
description: Clean Architecture, hexagonal architecture, ports and adapters, dependency rule, and domain-centric layering. Auto-load when designing architecture, choosing layers, discussing the dependency rule, ports, adapters, or keeping the domain free of framework code.
---

# Clean Architecture

## The one rule
**Source-code dependencies point inward.** Inner circles know nothing about outer ones.

```
[ Frameworks & Drivers ]   ← HTTP, DB, UI, CLI
  [ Interface Adapters ]   ← controllers, presenters, gateways
    [ Use Cases ]          ← application-specific business rules
      [ Entities ]         ← enterprise-wide business rules
```

If a use case imports the ORM, the rule is broken.

## Ports and adapters
- **Port** — interface owned by the domain describing what it needs (`UserRepository.find(id)`).
- **Adapter** — implementation in the outer layer (`PostgresUserRepository`).
- Domain depends on ports. Composition root wires adapters to ports at startup.

## Keeping the domain pure
- No imports of HTTP, SQL, ORM types, JSON libraries, or wall-clock time from the domain.
- Pass side-effects in as interfaces (`Clock`, `IdGenerator`, `Repository`).
- Domain types are plain data + behavior — no framework annotations.

## Boundary crossings
- Cross layers only via data structures the inner layer defines.
- Outer layers translate to/from these structures. Never leak an ORM entity into a use case.

## Testing payoff
- Use cases are unit-testable with fake adapters.
- Integration tests live at the adapter boundary.
- Framework tests (HTTP, DB) stay narrow because business rules are elsewhere.

## When NOT to apply
- Throwaway scripts and prototypes — flat is fine.
- Obvious CRUD with no domain logic — a single service file is clearer than four layers.
- Tiny internal tools where ceremony cost exceeds change cost.

## Drift smells
- Repositories returning ORM objects instead of domain types.
- Use cases importing HTTP request/response types.
- Presenters holding business rules.
- `utils` packages imported by the domain.

## Layer import rules

| Layer | Can import | Must NOT import |
|-------|-----------|----------------|
| Domain | Standard library only | Application, Infrastructure, Framework |
| Application | Domain | Infrastructure, Framework |
| Infrastructure | Domain, Application | Framework (except its own SDK) |
| Framework/UI | All layers | — |

Layers don't require separate modules. A directory per layer suffices: `domain/`, `app/` (or `usecase/`), `infra/`, `ui/`.

## Decision aid
Ask: "If we swapped the database / web framework / message bus, which files change?" Only the adapters should.

## Common Excuses — and Why They're Wrong

| Excuse | Reality |
|--------|---------|
| "Everything in one package is simpler" | Simpler to write, harder to maintain. When DB logic changes, domain tests break — that's the coupling tax. |
| "Separate directories is over-engineering" | Directories are free. The cognitive load of finding where logic lives in a flat structure is not. |
| "The framework requires this structure" | Frameworks constrain the outermost layer. Inner layers owe the framework nothing. Adapt at the boundary. |
| "I'll refactor when it gets bigger" | You won't. Refactoring a coupled codebase is 10× harder than building with boundaries from the start. |
| "This is just a prototype" | If it might ship, apply the dependency rule now. Retrofitting layers onto a flat codebase is the most expensive refactor. |

## Red Flags — Stop and Reassess

- Domain type importing `database/sql`, `net/http`, or any external service SDK
- Business logic function that takes a database connection as a parameter
- Free function implementing business logic that should be entity behavior
- "This is just CRUD" used to skip layer separation when business rules exist
- Repositories returning ORM objects instead of domain types
- Use cases importing HTTP request/response types

## If You Catch Yourself Thinking…

| Thought | What to Do Instead |
|---------|--------------------|
| "I'll put it all in one package for now" | Run the layer assignment test on each type — separate by result. |
| "Interfaces are overkill here" | Does the dependency cross a layer? Yes → interface. No negotiation. |
| "Let me import the store directly, it's faster" | Faster to write, impossible to test in isolation. Define the interface. |
| "This is too small for Clean Architecture" | Apply proportionally. A directory per layer costs nothing. Skip only for true scripts/prototypes. |
