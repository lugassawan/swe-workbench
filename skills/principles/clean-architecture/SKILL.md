---
name: clean-architecture
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

## Decision aid
Ask: "If we swapped the database / web framework / message bus, which files change?" Only the adapters should.
