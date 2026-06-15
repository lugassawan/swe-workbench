---
name: principle-data-modeling
description: "Data modeling: relational vs document vs KV vs graph selection, normalization depth, indexing strategy, hot-key avoidance, schema evolution via expand–contract, query-first design, retention and archival. Auto-load when designing schemas, choosing a storage paradigm, discussing normalization or denormalization, schema evolution, indexing strategy, hot-key avoidance, query-first design, or data retention."
---

# Data Modeling

## The one rule
**Model for the queries you'll run, not the data you have.**

Start by listing access patterns. Let them shape tables, indexes, and storage choice. A schema designed from the entity graph first almost always requires painful rework once query patterns solidify.

## Storage paradigm selection

| Access pattern | Best fit | Avoid |
|---|---|---|
| Joins across entities, strong consistency, ad-hoc queries | Relational (Postgres, MySQL) | Document — you'll re-implement joins in app code |
| Flexible schema, deep nested reads, document-centric writes | Document (MongoDB, Firestore) | Relational — schema rigidity fights you |
| Point lookups, extreme throughput, mostly single-key reads | KV / wide-column (Redis, DynamoDB single-table) | Relational — joins at scale hurt. Note: DynamoDB supports composite keys and GSIs; it can serve multi-entity patterns when modeled carefully. |
| Highly connected data, path/graph traversal queries | Graph (Neo4j, Amazon Neptune) | Relational — recursive CTEs degrade fast |

**Inversion test:** if your primary latency-bound read requires unbounded recursive joins or joins that cannot be satisfied by available indexes, your storage paradigm may be wrong for the access pattern.

## Normalization vs denormalization

Normalize when:
- Write throughput is high and reads are secondary.
- Data consistency across many rows matters more than read latency.
- Access patterns are unknown (start normalized; denormalize with evidence).

Denormalize when:
- Reads dominate and latency SLOs are tight.
- The duplicated data changes infrequently.
- You own the write path and can keep copies consistent.

The cost of denormalization is paid in write complexity and consistency risk, not storage.

## Indexing strategy

- **Column order in composite indexes:** put the equality column first, then the range column. `(status, created_at)` serves `WHERE status = 'active' ORDER BY created_at` — the reverse does not.
- **Covering indexes:** include non-key columns via `INCLUDE` (Postgres) or as trailing key columns (MySQL) to avoid heap fetches on hot paths. Keep the key column order (equality → range) intact.
- **Partial/filtered indexes:** index only rows that match the predicate. `WHERE deleted_at IS NULL` shrinks the index by orders of magnitude on soft-delete tables.
- **Write amplification:** every index is a write cost. Add indexes on read evidence, not speculation.

## Hot keys and hot partitions

Symptoms: P99 latency spikes on a single shard; one database CPU at 100% while others idle.

Detection: per-key / per-partition read and write metrics, not aggregate throughput.

Mitigations:
- **Key salting** — append a random suffix (0–N) to the key; fan-out reads and merge client-side.
- **Write batching** — coalesce high-frequency writes to the same key before flushing. Safe only for idempotent or last-write-wins semantics; do not buffer writes that require durability guarantees.
- **Read replicas** — route reads off the primary for frequently-read hot keys.
- **Cache tier** — TTL cache in front of the hottest 1% of keys absorbs most of the read load.

## Schema evolution: expand–contract

Never change a column in place. The wire-safe sequence:

1. **Expand** — add the new column/field (nullable, with default). Begin dual-writing both old and new in the same deploy. Deploy.
2. **Backfill** — populate the new column for all rows written before dual-write was active. Verify row count; do not skip rows created between Expand and this step.
3. **Read cutover** — switch reads to the new column; fall back to old only for rows where new is NULL. Deploy.
4. **Contract** — remove the old column/field once all reads use the new path. Deploy.

Each step is independently deployable and rollback-safe.

## Query-first modeling checklist

Before touching a schema:
- [ ] List every access pattern (reads and writes, by frequency).
- [ ] Assign each pattern a storage tier and an index.
- [ ] Identify which patterns cross entity boundaries — those are join or fan-out candidates.
- [ ] Verify the primary read path needs ≤2 indexes.

## Retention and archival

- **TTL expiry** — for ephemeral data (sessions, OTP tokens, rate-limit counters). Set at write time; let the store clean up.
- **Soft delete** (`deleted_at`)— for audit trails and recovery windows. Add a partial index on `deleted_at IS NULL`.
- **Archive tier** — move cold rows to a separate table or cold storage after a defined age. Query hot tables only.
- **Legal hold** — never auto-delete data flagged as in-litigation, even if TTL fires. Implement a `hold` flag that blocks all deletion paths.
- **Cascade audit** — if parent rows are hard-deleted, verify FK cascade actions do not silently delete held child records.

## When NOT to apply

- Throwaway scripts and one-shot data migrations.
- Single-table CRUD with exactly one reader and no future growth.
- Early prototypes where access patterns are still being discovered — sketch first, harden once patterns stabilize.

## Drift smells

- `data JSONB` column holding fields that are queried in `WHERE`, `ORDER BY`, or `JOIN` conditions — those should be real columns with indexes.
- Indexes added per-incident with no coverage review — sign of schema designed before access patterns.
- `SELECT *` in production queries — leaks column layout changes into application code.
- No foreign keys in a relational store — consistency guarantees moved to application layer.
- Nullable columns proliferating — signals missing domain modeling; most should have sensible defaults.
- Schema migration that drops or renames a column in a single step without expand–contract.

## Common Excuses — and Why They're Wrong

| Excuse | Reality |
|---|---|
| "We'll optimize the schema later." | Later never comes. Retrofitting indexes and constraints onto a live 100M-row table is expensive, risky, and embarrassing. |
| "The ORM handles it." | The ORM maps objects to tables; it does not choose the right storage paradigm or index order for your access patterns. |
| "Postgres can do anything." | It can, but at a cost. Running a graph traversal in recursive CTEs on 50M rows is possible; it's not the right tool. |
| "We'll just add an index." | Every index slows writes. Adding indexes without retiring unused ones is technical debt that compounds. |
| "JSON blobs are flexible." | They are, until you need to query inside them. Then you've built a document store inside a relational store, with none of the document store's query optimizations. |
