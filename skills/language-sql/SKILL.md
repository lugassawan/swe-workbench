---
name: language-sql
description: SQL idioms — query tuning, table definitions, constraints, transactions, and pagination. Auto-load when working with .sql files or migrations, or when the user mentions SELECT, JOIN, EXPLAIN, CTE, window functions, or SQL indexes.
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

## DDL migration footguns (MySQL 8.0)
- `BEGIN`/`COMMIT` around DDL grants no atomicity in MySQL: each DDL statement auto-commits independently, wrapper or not. Treat it as a readability convention, not a safety net.
- A run killed mid-way (CI timeout, dropped connection) leaves earlier statements committed while the tracker records nothing — drifted schema, no audit trail. Plan recovery forward-only; make each statement independently re-runnable.
- `ADD COLUMN` already gets `ALGORITHM=INSTANT` (metadata-only) by default on 8.0.12+. An explicit `INPLACE` or `COPY` overrides that default and forces a full table+index rebuild — treat as a defect unless the column is genuinely `INSTANT`-ineligible (pre-8.0.29: end-of-table adds only; `ROW_FORMAT=COMPRESSED` always). `DROP COLUMN` only becomes `INSTANT`-eligible on 8.0.29+.
- `ADD INDEX`/`DROP INDEX` are the exception: `ALGORITHM=INPLACE, LOCK=NONE` is correct and expected here — `INSTANT` cannot build an index, so do not flag `INPLACE` on index DDL.
- Check `information_schema.tables.table_rows` before choosing an approach; migration cost is invisible in the DDL text and scales with table size, not statement count.
- On tables over 50M rows, split `INSTANT`-eligible column adds into their own migration file, separate from index builds — a mid-run failure then leaves a smaller, more legible partial state.

```sql
-- Suspect: forces a full rebuild MySQL would otherwise skip (8.0.12+ defaults to INSTANT)
ALTER TABLE orders ADD COLUMN notes TEXT, ALGORITHM=INPLACE, LOCK=NONE;

-- Preferred: pin INSTANT explicitly — errors loudly if ineligible instead of
-- silently degrading to INPLACE/COPY the way an omitted ALGORITHM clause would
ALTER TABLE orders ADD COLUMN notes TEXT, ALGORITHM=INSTANT;

-- Correct: INSTANT cannot build an index; INPLACE is required here
ALTER TABLE orders ADD INDEX idx_orders_customer_id (customer_id), ALGORITHM=INPLACE, LOCK=NONE;
```

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

## Tooling
- **Format:** `sqlfluff fix --dialect <dialect> .` (replace `<dialect>` with e.g. `ansi`, `postgres`, `bigquery` — check `.sqlfluff` config or project README)
- **Lint:** `sqlfluff lint --dialect <dialect> .`
- **Test:** engine-specific (pgTAP for PostgreSQL, `dbt test` if using dbt) — see Testing below

## Testing
- pgTAP for in-database assertions (`results_eq`, `throws_ok`), run via `pg_prove`; `dbt test` for `unique`/`not_null`/`relationships` in transformation projects.
- Wrap each test in `BEGIN … ROLLBACK` for isolation — no shared state or leftover rows between tests.
- Seed deterministic fixtures per test; don't depend on ambient row counts or implicit ordering.
- Assert on `EXPLAIN` output (index scan vs seq scan) to catch query-plan regressions.

```sql
BEGIN;
SELECT plan(1);

INSERT INTO users (id, active) VALUES (1, true), (2, true), (3, false);

SELECT results_eq(
    'SELECT count(*) FROM users WHERE active',
    ARRAY[2::bigint]
);

SELECT * FROM finish();
ROLLBACK;
```

## Avoid
- Schema changes without rollback or compatibility planning.
- Unbounded queries in production paths.
- Relying on implicit ordering without `ORDER BY`.
- Wrapping MySQL DDL in `BEGIN`/`COMMIT` for atomicity, or an unnecessary `ALGORITHM=INPLACE`/`COPY` on a column add/drop — see DDL migration footguns above.
- Never build SQL by concatenating untrusted input — use parameterized queries or prepared statements. ORM raw-query escape hatches (e.g. Django's `extra()`, SQLAlchemy's `text()`) are equally dangerous. See `swe-workbench:principle-security`.
