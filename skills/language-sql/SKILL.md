---
name: language-sql
description: SQL idioms - query tuning, EXPLAIN plans, table definitions, constraints, indexes, transactions, window functions, CTEs, and pagination. Auto-load when working with .sql files or migrations, or when the user mentions SQL syntax, SELECT, JOIN, EXPLAIN, CTE, window functions, transaction isolation, deadlocks, or SQL indexes.
---

# SQL

## Query optimization basics
- Start with the access pattern: filters, joins, grouping, sorting, and result size.
- Index columns used for selective `WHERE`, join keys, and stable `ORDER BY` clauses.
- Prefer narrow projections over `SELECT *`; return only the columns callers need.
- Avoid accidental row multiplication in joins; check cardinality before adding `DISTINCT`.
- Watch for N+1 query loops at application boundaries.

## EXPLAIN and EXPLAIN ANALYZE
- Use `EXPLAIN` to inspect the planned access path before changing indexes or query shape.
- Use `EXPLAIN ANALYZE` when you need actual timing and row counts; run it against safe data and statements.
- Compare estimated vs actual rows. Large gaps often mean stale statistics, skewed data, or missing predicates.
- Optimize the highest-cost operation first, but confirm the full query got faster.

## Schema design
- Model durable facts, not current screens. Let queries influence indexes, not table names.
- Choose primary keys deliberately; use foreign keys for integrity unless there is a measured reason not to.
- Normalize to remove update anomalies, then denormalize only for proven read pressure.
- Encode invariants with constraints: `NOT NULL`, `UNIQUE`, `CHECK`, and referential actions.
- Plan migrations as expand-and-contract changes when existing clients need compatibility.

## Transactions and isolation
- Keep transactions short; do not wait on users or remote services while holding locks.
- Pick the weakest isolation level that preserves correctness for the workflow.
- Know the anomalies you are allowing: dirty reads, non-repeatable reads, phantoms, and write skew.
- Use optimistic concurrency with version columns when conflicts are rare and retriable.

## Deadlock avoidance
- Touch shared tables and rows in a consistent order across code paths.
- Lock only what you need, as late as possible, and commit as soon as the invariant is protected.
- Add retry logic for deadlock and serialization failures; they are expected under contention.
- Index foreign keys and hot predicates so updates do not scan and lock more rows than intended.

## Window functions
- Use window functions for rankings, running totals, deduplication, and "top N per group" queries.
- Keep `PARTITION BY` and `ORDER BY` explicit; frame clauses matter for aggregates.

```sql
SELECT customer_id, order_id, total,
       row_number() OVER (
         PARTITION BY customer_id
         ORDER BY created_at DESC
       ) AS recency_rank
FROM orders;
```

## CTEs vs subqueries
- Use CTEs to name meaningful intermediate results or reuse the same derived relation.
- Use subqueries when the scope is local and the surrounding query stays readable.
- Check your database's optimizer behavior; some engines inline CTEs, others may materialize them.
- Do not use CTEs as a performance hint unless the engine documents that behavior.

## Pagination patterns
- Prefer keyset pagination for large or frequently changing result sets.
- Use `LIMIT`/`OFFSET` only for small, stable lists; deep offsets get slower and can skip or duplicate rows.
- Make ordering deterministic with a unique tie-breaker.

```sql
SELECT id, customer_id, created_at, total
FROM orders
WHERE (created_at, id) < (:last_created_at, :last_id)
ORDER BY created_at DESC, id DESC
LIMIT 50;
```

## Avoid
- Schema changes without rollback or compatibility planning.
- Unbounded queries in production paths.
- Relying on implicit ordering without `ORDER BY`.
- Never build SQL by concatenating untrusted input — use parameterized queries or prepared statements. ORM raw-query escape hatches (e.g. Django's `extra()`, SQLAlchemy's `text()`) are equally dangerous. See `swe-workbench:principle-security`.
