---
name: principle-ddd
description: Domain-Driven Design — bounded contexts, aggregates, entities, value objects, ubiquitous language, and domain events. Auto-load when modeling a complex domain, splitting services, designing aggregates, or aligning code with business language.
---

# Domain-Driven Design

DDD is a toolkit for **complex domains**. For CRUD, it is overkill.

## Strategic design

### Ubiquitous language
Every important concept in code uses the same word the domain experts use. If marketing says "subscription" and code says "userPlan", you have a translation tax forever. Rename.

### Bounded contexts
A bounded context is a boundary inside which a term has exactly one meaning. "Order" in Checkout is not the same entity as "Order" in Fulfillment — it just shares a name.
- One team, one context is the ideal.
- Cross-context communication goes through explicit contracts (events, APIs).
- Shared databases across contexts are an anti-pattern.

### Context map
Document how contexts relate: Partnership, Customer/Supplier, Conformist, Anticorruption Layer, Published Language, Shared Kernel, Separate Ways. Pick the relationship intentionally.

## Tactical design

### Entity
Identity persists through change. `User{id, name}` — renaming doesn't change the user.

### Value object
Identity-less, immutable, compared by value. `Money{amount, currency}`, `EmailAddress`, `DateRange`. Prefer aggressively — eliminates primitive obsession bugs.

### Aggregate
A cluster of entities and value objects treated as one consistency boundary. The **aggregate root** is the only entry point; outside code cannot hold references to internal entities.
- Keep aggregates small — large ones cause contention.
- One transaction, one aggregate. Cross-aggregate coordination happens via domain events.

### Repository
Collection-like interface for loading and persisting aggregates. Port in domain layer; implementation in infrastructure.

### Domain event
Something meaningful that happened. `OrderPlaced`, `PaymentFailed`. Emit from aggregates; handle in application services or other contexts.

### Domain service
Stateless domain logic that does not belong on a single entity (e.g., a transfer between two accounts).

## When DDD is overkill
- Simple CRUD apps.
- Technical utilities (a scheduler, a logger).
- Prototypes where the domain is not yet understood — premature DDD freezes the wrong model.

## Signals you need DDD
- Multiple teams colliding in one codebase.
- Business rules hidden inside controllers or stored procedures.
- Experts and developers using different words for the same thing.
- Transactions spanning unrelated data.

## Signs you specifically need Full DDD
- Multiple entities must change atomically (→ aggregates + unit of work).
- Business events trigger cascading actions across the domain (→ domain events).
- Different teams own different parts of the domain (→ bounded contexts + context map).

## Pattern Selection Quick Reference

| Complexity | Domain patterns | Repository pattern | Example |
|------------|----------------|-------------------|---------|
| **No business rules** | Plain DTOs | Direct data access | Settings CRUD, preferences |
| **Simple rules** | Entities with methods, value objects | Interface in domain layer | Price alerts with threshold logic |
| **Complex invariants** | Aggregates, domain events, specifications | Interface + unit of work | Portfolio rebalancing with multi-asset constraints |

**Light DDD is the floor when business rules exist**: entity behavior + repository interfaces + value objects for constrained types are non-negotiable even for "simple" cases.
