---
name: principle-performance
description: Performance engineering principles — latency vs throughput, profile-before-optimize discipline, Big-O instincts for common patterns, allocation and GC pressure, data locality and cache-friendliness, N+1 queries on a list endpoint. Auto-load when reviewing hot-path code, choosing data structures, designing batch or streaming pipelines, hunting allocations or GC pauses, weighing latency trade-offs, considering caching, detecting N+1 queries on list endpoint calls, or evaluating scalability.
---

# Performance

Performance bugs are design bugs. They are cheapest to fix before the first line of code is written. This skill teaches design-time discipline — choosing the right algorithm, data structure, and access pattern — not runtime profiler operation.

## Latency vs Throughput

They pull in opposite directions; name the goal before optimizing.
- Latency: time to serve one request. Throughput: requests served per unit time. Improving one often degrades the other.
- Tail latency (p99, p999) is a separate budget from mean latency — do not let averages hide outliers.
- Batching and buffering improve throughput at the cost of per-item latency; state this trade-off explicitly.
- Choose the objective first: a real-time API and a batch pipeline have different success criteria.

## Profile Before You Optimize

Measurement beats intuition; no fix without a hot path identified by data.
- Identify the bottleneck with a profiler before changing code — optimizing a path that accounts for 5% of runtime cannot yield more than a 5% total improvement, no matter how perfect the fix.
- Benchmark before and after each change; a "feels faster" claim is not evidence.
- Most code is cold; optimize only the identified hot path. Premature optimization is applied to the wrong place.
- A profile that surprises you is information; a profile you skipped is a bug waiting to be filed.

## Big-O Where It Bites

Algorithmic complexity matters when N grows; the right abstraction is cheaper than any constant-factor tweak.
- Nested loops over collections are O(n²) by default — verify that the outer N is bounded and small.
- Membership tests on lists are O(n); use a hash set when the check is inside a loop.
- String concatenation inside a loop builds O(n²) bytes; accumulate then join once outside the loop.
- Sort once, query many times — precompute sorted order or indexes when access patterns allow.
- Accidental quadratic is the most common performance regression; review any loop whose body touches a collection.

## Allocation & GC Pressure

Every allocation is work; allocation rate drives GC pause frequency and duration.
- Allocations on the hot path accumulate — a tight loop that allocates per iteration can dominate GC time.
- Reuse buffers, pools, or pre-allocated slices; avoid constructing intermediate objects that are immediately discarded.
- Value types (stack-allocated structs, primitives) beat heap-allocated objects on hot paths.
- Immutability is a correctness tool with a cost: copying for safety is fine in cold code, expensive in hot code.
- Profile allocation rate, not just CPU — GC pauses show up as latency spikes, not CPU%.

## Data Locality

Access patterns that match memory layout are faster than clever but scattered code.
- Arrays of values beat arrays of pointers on hot paths — the CPU prefetcher handles sequential access, not pointer chasing.
- Structs-of-arrays (SoA) outperform arrays-of-structs (AoS) when only one field is accessed per loop iteration.
- Sequential access patterns are predictable and prefetch-friendly; random access patterns are not.
- Profile cache misses before restructuring data layouts — the gain varies widely by workload.

## N+1 and the Database Boundary

One query per iteration is the most common silent performance killer.
- An ORM that lazy-loads relations inside a list handler issues N+1 queries by default; always verify the query count.
- Batch, join, or preload: fetch all related records in one query, then associate in memory.
- Eager-loading defaults beat lazy-loading defaults in most list and aggregate endpoints.
- Measure query count at the boundary (query logs, explain plans) — not only wall-clock time.
- "We'll cache it later" is not a query strategy; the cache miss path is still N+1.

## Caching

Caching trades freshness and memory for latency — earn it with a profile and a clear invalidation plan, not a hunch.
- Add a cache only after measuring; a cache that hides an N+1 query still runs N+1 queries on a miss (see `N+1 and the Database Boundary` above).
- Layers — in-process (L1, fastest, per-node, risks drift between replicas) → distributed (L2, shared, costs a network hop) → CDN/edge (static content and cacheable GETs). See `principle-api-design#REST vs RPC vs Event-Driven` for HTTP cacheability.
- Invalidation strategies — cache-aside (lazy, app-managed, the default: read from cache; on miss, load from origin, populate, return) vs write-through (write populates cache synchronously, strong consistency, higher write cost) vs write-behind (async flush, fast writes, loss window on crash). Prefer TTL + explicit bust on known writes; see `principle-event-driven#Event Sourcing` for cache/projection drift.
- TTL — size TTL to data volatility, not a round number. Short TTL = fresher data + more origin hits; long TTL = staler data + cheaper reads.
- Stampede prevention — when a hot key expires, concurrent misses dogpile the origin. Use single-flight or a mutex so one caller recomputes while others wait, or use probabilistic early expiry to spread recomputation. See `principle-resiliency#Graceful Degradation` for serving stale-on-error as fail-soft.

> See `examples/` for cache-aside with single-flight in C#, Go, Java, Kotlin, Python, Ruby, Rust, Swift, and TypeScript (read on demand — not auto-loaded).

## When Pre-Write Performance Thinking is Overkill

- Scripts that process fixed, small inputs and run rarely or once.
- Throwaway prototypes where correctness is the only requirement.
- Cold paths: initialization code, admin-only endpoints under negligible load.
- One-time migrations on small, bounded datasets where row count is verified before run.
- Internal tooling with known-small N (under a few hundred items, single-digit users).
- Apply YAGNI: do not optimize for scale that does not yet exist and may never arrive.

## Red Flags

| Flag | Problem |
|------|---------|
| Optimization without a profile | Speedup applied to a path that may not be the bottleneck |
| O(n²) loop over user-controlled input | N is unbounded; attacker can trigger quadratic blowup |
| Allocation inside inner loop | High allocation rate causes GC pauses at the worst time |
| Lazy ORM relation on list endpoint | Guarantees N+1 queries at runtime |
| "We'll cache it later" | Cache masks a bad access pattern; the cache-miss path is still slow |
| Cache invalidation as an afterthought | Stale reads with no owner; correctness bugs appear only under write load |
| Unbounded cache growth / no eviction policy | Memory blows up under load; OOM kills the process |
| No stampede guard on a hot key | Concurrent cold misses dogpile the origin; the cache makes the outage worse |
| Tail latency ignored in SLOs | p99 outliers hit real users; mean metrics hide them |
| String concat in loop | O(n²) byte copies; accumulate and join once outside the loop |
