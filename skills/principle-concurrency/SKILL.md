---
name: principle-concurrency
description: Concurrency principles — race conditions, deadlock, livelock, starvation, structured concurrency, cancellation propagation, backpressure, lock-free primitives, atomics, memory models, choosing between mutex vs channel vs actor vs semaphore vs CAS. Auto-load when designing concurrent code, debugging a race condition, fixing a deadlock, propagating cancellation, choosing a synchronization primitive, designing worker pools, or reasoning about goroutine/thread/task lifetimes.
---

# Concurrency

Concurrency is a correctness hazard first, a performance tool second. Prove correctness before optimizing.

## Failure Modes

**Race condition** — two goroutines/threads read and write shared state without synchronization; result is non-deterministic. **Fix:** mutex, channel, or atomic.

**Deadlock** — two or more tasks each hold a lock the other needs; all block forever. **Fix:** consistent lock-acquisition ordering; prefer higher-level primitives.

**Livelock** — tasks keep changing state in response to each other but make no progress; common in retry loops that back off identically. **Fix:** add jitter; use backpressure signals.

**Starvation** — a low-priority task never gets scheduled because high-priority tasks monopolize a resource. **Fix:** fair queues; priority inheritance; rate limits.

**Lost wakeup** — a condition-variable signal fires before the waiter starts waiting; waiter sleeps forever. **Fix:** always check the predicate in a loop; use atomic flags.

**ABA problem** — a CAS succeeds because a value returned to A, masking an intervening change. **Fix:** use version tags or hazard pointers; prefer higher-level data structures.

## Structured Concurrency

Child task lifetimes must nest inside the parent's lifetime. No orphan goroutines or threads.
- When the parent exits, all children are cancelled first.
- Errors propagate up — a child error surfaces to the parent, not to a background log line.
- Never fire-and-forget unless the lifetime is explicitly managed (e.g., a top-level worker pool with a shutdown hook).
- For language-specific structured concurrency APIs, see `language-go` (errgroup, context) and your platform's task group primitives.

## Cancellation

Concurrency requires cooperative cancellation — you cannot safely kill a thread mid-operation.
- Pass a context or cancellation token down the call stack; never rely on thread interruption.
- Check for cancellation at every I/O boundary and between long computation steps.
- Release resources (locks, file handles, connections) before acknowledging cancellation.
- Do not swallow cancellation signals — propagate them or translate them into a clean shutdown signal.

## Backpressure

Unbounded queues hide a broken producer/consumer balance until memory is exhausted.
- Use bounded queues with explicit drop or block policies.
- Ask "what happens when downstream is slower than upstream?" before writing any queue.
- **Drop oldest** — acceptable for telemetry and non-critical real-time data.
- **Block producer** — correct for ordered pipelines where data loss is unacceptable.
- **Error/circuit-break** — correct for RPC fan-out where partial failure is worse than full failure.

## Primitive Selection

**Mutex** — shared mutable state with exclusive access; short critical sections only.
**Use when:** multiple writers share an in-memory structure; critical section is O(1) or near.
**Costs:** lock contention serializes all callers; holding a lock across I/O causes convoy problems.

**Channel** — ownership transfer, pipeline staging, fan-out/fan-in.
**Use when:** passing a value from one goroutine/task to another; buffered for throughput, unbuffered for synchronization.
**Costs:** overhead vs mutex for simple counters; wrong buffer size silently causes deadlock.

**Actor** — state encapsulated behind a single mailbox; all access serialized through message passing.
**Use when:** complex mutable state is accessed by many concurrent callers; prefer isolation over sharing.
**Costs:** message copying overhead; harder to express synchronous request-response.

**Atomic / CAS** — lock-free fast path for counters, flags, and pointer swaps.
**Use when:** a single variable needs concurrent update; profiling shows mutex is the bottleneck.
**Costs:** memory-ordering semantics are subtle; composing multiple atomics is not itself atomic.

**Semaphore** — bounded resource pool (connection pool, worker pool, API rate limit).
**Use when:** limit concurrent access to a resource to N callers.
**Costs:** starvation possible without fair queueing.

> For Go-specific idioms (goroutine lifecycles, channel patterns, `sync` package): see `language-go`.

## When Concurrency is Overkill

- Sequential is correct until a profiler identifies a throughput or latency bottleneck.
- Single-core environments or scripts where parallelism is unavailable.
- Synchronization complexity outweighs the speedup — measure first.

## Red Flags

| Flag | Problem |
|------|---------|
| `sleep` used to synchronize goroutines or threads | Sleep-based sync is a race condition with a timing window; use channels or barriers |
| Double-checked locking without atomics or memory fences | Compilers and CPUs reorder; the outer check is not safe without proper memory ordering |
| Unbounded channel or queue | Hides backpressure; exhausts memory under sustained load |
| Lock held across a network call or database query | Serializes all callers for the full I/O duration; severe performance cliff |
| Race "fixed" by adding more locks | Deadlock risk grows with lock count; redesign ownership instead |
