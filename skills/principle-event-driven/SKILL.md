---
name: principle-event-driven
description: Event-driven architecture — event sourcing, CQRS, sagas, choreography vs orchestration, schema evolution, consumer groups, partitions, ordering, idempotent handlers, outbox pattern, dead letter queues. Auto-load when designing event-driven systems, evaluating event sourcing or CQRS, planning saga workflows, evolving event schemas across consumers, configuring consumer groups or partitions, implementing idempotent consumers or the outbox pattern, managing dead letter queues, or assessing whether event-driven architecture fits the problem.
---

# Event-Driven Architecture

The log is the source of truth: producers emit immutable events; consumers react asynchronously. This decouples services at deployment and operational boundaries and lets new consumers replay history — at the cost of eventual consistency and significantly more failure surface area than synchronous calls.

## Event Sourcing

Store every state change as an immutable event; derive current state by replaying the log. The aggregate's current state is a projection, not the record of truth.

- Snapshots cap replay cost: persist a projected state checkpoint every N events and replay only from the latest snapshot.
- Projections are disposable — design them to be rebuilt by replaying; avoid hand-rolled caches that drift from the log.
- Event store must be append-only; mutating or deleting events destroys the audit trail and breaks replaying consumers.
- GDPR erasure: store PII in a side-table and tombstone the key rather than mutating event history.

## CQRS (Command Query Responsibility Segregation)

Separate the write model (commands that mutate state) from the read model (queries over projections). Often paired with event sourcing but independent of it.

- Read replicas can be denormalized and tuned for specific query shapes without polluting the write model.
- Consistency lag between write and read models is a feature contract, not a bug — document the SLA.
- Avoid CQRS in simple CRUD services; indirection cost exceeds benefit until query and write shapes diverge significantly.

## Sagas — Choreography vs Orchestration

Long-running transactions spanning services must be modeled as sagas with explicit compensation steps.

**Choreography** — each service emits events and reacts to others; no central coordinator.
- Low coupling; hard to trace and debug as the workflow grows beyond two or three participants.

**Orchestration** — a central saga orchestrator drives the workflow and issues commands to participants.
- Easier observability and rollback reasoning; introduces a single point of coordination and coupling.
- Prefer orchestration when compensation logic is non-trivial or the workflow has more than three participants.

Compensation steps must be idempotent — the orchestrator may retry them on failure.

## Event Schema Evolution

Consumers and producers deploy independently; schema drift causes silent deserialization failures.

- **Backward-compatible changes** (add optional field): safe to deploy producer first.
- **Conditionally breaking** (add enum value): safe only if all consumers tolerate unknown values (e.g., JSON Schema with a catch-all default); for Avro or Protobuf under BACKWARD compatibility, treat as breaking — require a versioned event type and a dual-publish period.
- **Breaking changes** (rename field, remove field, change type): require a versioned event type and a dual-publish period.
- Prefer a schema registry (Confluent Schema Registry, AWS Glue) over ad-hoc JSON to enforce compatibility rules at publish time.
- Never rely on field ordering; always deserialize by name.

## Consumer Groups, Partitions, and Ordering

- Ordering is guaranteed only within a partition; partition by a key that co-locates events that must be ordered (e.g., all events for a given `entity_id` on the same partition).
- Consumer group parallelism is bounded by partition count — you cannot have more active consumers than partitions.
- Rebalance storms on group membership changes cause in-flight delays; use static group membership where supported.
- Cross-partition ordering requires application-level sequencing (vector clocks or monotonic sequence numbers).

## Idempotent Handlers and the Outbox Pattern

At-least-once delivery is the broker default; consumers must handle duplicate events without producing duplicate side effects.

- Use a stable event ID as the deduplication key; see `principle-api-design#Idempotency` for the storage pattern.
- The **outbox pattern** ensures atomicity between a database write and event publication: write the event to an `outbox` table in the same transaction as the domain change; a relay process publishes it to the broker. Eliminates the dual-write problem.
- For idempotency key design see `principle-api-design#Idempotency`; for retry budgets before DLQ routing see `principle-error-handling#Retries and Backoff`.

## Dead Letter Queues and Poison Messages

A dead letter queue (DLQ) is the fail-soft path for unprocessable messages — see `principle-resiliency#Fail-Fast vs Fail-Soft`.

- Always configure a DLQ; without one a poison message halts the entire partition indefinitely.
- Emit a structured alert on every DLQ write — silent DLQs hide data loss.
- Preserve the original payload, headers, and metadata so messages are replayable after the root cause is fixed.
- Define a replay SLA: stale DLQ messages replayed into a later system state may apply out-of-order effects.

## When Event-Driven Architecture is Overkill

- Simple CRUD with a single service and database; REST or RPC is cheaper and easier to reason about.
- Strong consistency required across the operation — sagas with compensation add complexity without benefit.
- Team has no operational experience with brokers; the operational burden exceeds the decoupling gain.
- Low event volume (fewer than hundreds per day); a message broker adds infrastructure cost for no throughput benefit.

## Red Flags

| Flag | Problem |
|------|---------|
| No partition key strategy | Events for the same entity land on different partitions; ordering lost |
| Dual-write without outbox | Crash between DB write and broker publish causes silent data loss |
| No DLQ configured | Poison message halts the partition; data backs up without alerting |
| Schema changes without versioning | Consumers fail silently on unexpected field shapes |
| Choreography saga with no compensating events | Partial failures leave distributed state permanently inconsistent |
| Idempotency check absent on consumer | At-least-once delivery produces duplicate side effects |
| Cross-partition ordering assumed without sequencing | Ordering guarantee breaks silently across partitions or brokers |
