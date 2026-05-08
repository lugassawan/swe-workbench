---
name: principle-resiliency
description: Resiliency principles — fault tolerance, partial failure, blast radius, failure domains, bulkheads, resource isolation, graceful degradation, fail-fast vs fail-soft, health checks, liveness vs readiness probes, cascading failure, gray failure, fault isolation. Auto-load when designing for partial failure, isolating dependencies via bulkheads, planning graceful degradation, choosing fail-fast vs fail-soft, configuring health/readiness/liveness probes, evaluating cascading failure risk, designing fallback paths, or reviewing system-level fault tolerance.
---

# Resiliency

Distributed systems fail partially, not totally. Resilience is the discipline of staying useful when components, networks, or dependencies degrade.

## Failure Domains

A failure domain is the set of components that fail together. Name failure domains before designing for them — unnamed domains produce unnamed blast radii.

- **Crash failure** — process exits; detectable immediately by the load balancer or orchestrator.
- **Slow failure** — process responds but takes too long; the most dangerous mode. Threads and connections fill; the caller eventually crashes too.
- **Gray/Byzantine failure** — process returns wrong data or errors intermittently; hardest to detect.
- **Partial failure** — some instances or shards fail while others serve normally.

Cascading failure: a degraded dependency holds resources long enough that the caller exhausts its own pools, propagating failure upstream. Root cause is almost always unbounded resource sharing across failure domains.

## Bulkheads

Named after ship compartments: isolate resource pools so a breach in one dependency does not exhaust resources for all others.

- Allocate a separate bounded connection pool, semaphore, or thread pool per downstream dependency.
- Never share a single pool across unrelated dependencies — a slow third-party API must not starve database connections.
- In multi-tenant systems, partition queues or workers per tenant to contain noisy-neighbor starvation.
- Size each bulkhead to the dependency's realistic concurrency ceiling, not the caller's maximum.

## Fail-Fast vs Fail-Soft

**Fail-fast** — surface the error immediately without attempting recovery.
**Use when:** an invariant is violated, the operation cannot be retried safely, or the system state is unrecoverable.
**Examples:** config missing at startup, corrupted schema, required auth service unreachable at boot.

**Fail-soft** — continue serving a degraded response using a fallback, stale cache, or reduced feature set.
**Use when:** the failed component is non-critical and a safe, non-misleading fallback exists.
**Examples:** recommendation service down → return empty list; search unavailable → hide the search bar.

Never fail-soft when the degraded response is actively misleading or could corrupt downstream state.

## Survive Faults at I/O Boundaries

Every I/O call must have a deadline. Call-site mechanics (timeouts, retry with backoff, circuit breakers) are covered in `principle-error-handling#Timeouts and Deadlines`, `principle-error-handling#Retries and Backoff`, and `principle-error-handling#Circuit Breakers`. System-level constraints:

- Retries are only safe on idempotent operations — see `principle-api-design#Idempotency`. A non-idempotent retry corrupts state; the retry budget does not excuse skipping idempotency design.
- Circuit breakers and bulkheads are complementary: deploy both for full dependency isolation.

## Graceful Degradation

Define degraded modes before incidents require them. "We'll figure it out" is not a fallback strategy.

- Fallback ladder (cheapest to most expensive to maintain): in-process cache → stale read replica → CDN-cached response → feature-toggle off → friendly error page.
- Shed expensive paths first: drop personalization, search, or aggregations before dropping core reads.
- Read-only mode is a valid degraded state for write-heavy systems when the write path fails.
- Feature toggles allow disabling non-critical paths without a deploy.

## Health Checks

**Liveness** — is the process alive? A failed liveness probe triggers container restart. Only fail liveness on truly unrecoverable conditions (deadlock, corrupted runtime state). Failing liveness during a dependency outage causes restart storms.

**Readiness** — is the process ready to serve traffic? A failed readiness probe removes the instance from rotation without restarting. Fail readiness when a required upstream is unavailable.

**Startup** — is the process still initializing? Prevents liveness from killing a slow-booting instance (cache warm, schema migration).

Shallow check: port open, fast HTTP 200. Always-on.
Deep check: validates dependency connectivity. Readiness only — never liveness.
Cascading-check trap: if every instance polls every dependency on each health interval, a slow dependency produces a check storm that looks like total outage.

For SLI/SLO framing of availability signals, see `principle-observability#SLI / SLO / Error Budget`.

## When Resiliency Engineering is Overkill

- Single-process tools with no network dependencies; crash-and-restart is the recovery.
- Batch jobs where idempotent restart is sufficient failure handling.
- Prototypes with one developer and no production traffic.
- Internal tools where one team owns both ends of every dependency.

## Red Flags

| Flag | Problem |
|------|---------|
| Single connection pool shared across all dependencies | Slow dependency exhausts connections for every other caller |
| Retry without idempotency | Non-idempotent retries corrupt state; budget wasted |
| Liveness probe that calls a downstream service | Dependency outage triggers container restart storm |
| Deep health check on every load-balancer poll interval | Health-check storm makes partial outage appear total |
| No explicit degraded mode for non-critical paths | Fallback invented under incident pressure |
| Fail-soft returning a misleading or stale result | User confusion or downstream data corruption |
| No per-dependency resource isolation | Any slow caller can exhaust all threads or connections |
