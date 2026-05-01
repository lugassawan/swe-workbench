---
name: principle-error-handling
description: Error handling principles — errors as values vs exceptions, error classification (transient/permanent/programmer), wrapping and context chains, sentinel vs typed vs coded errors, retry with exponential backoff and jitter, timeouts and deadlines, circuit breakers and bulkheads, log-once boundary discipline. Auto-load when discussing errors as values, Result type, exception handling, retry, exponential backoff, jitter, circuit breaker, fail fast, fail soft, idempotent retry, error wrapping, timeouts, or deadlines.
---

# Error Handling

Errors are part of the contract. Handling them is not defensive programming — it is the design.

## Errors as Values vs Exceptions

Use the language's native error style; don't fight it.
- **Go** `error` values, **Rust** `Result<T, E>`, **TypeScript** typed unions: errors are explicit return paths, visible in signatures, handled by callers.
- Exceptions (Java, Python, C#) work best for truly unexpected conditions — programmer errors, not business failures.
- Reserve `panic` / `throw` / unchecked exceptions for unrecoverable programmer errors. Expected failures (network timeout, not found) must be value-level errors.

## Classify Before Handling

Not all errors deserve the same response.
- **Transient** — network blip, timeout, lock contention: retry with backoff (fail soft — degrade gracefully while recovering).
- **Permanent** — bad input, not found, permission denied: fail fast — surface immediately to the caller, never retry.
- **Programmer** — nil deref, index out of bounds, invariant violated: panic/crash, fix the code.
- Misclassifying a permanent error as transient wastes retry budget and delays the caller.

## Wrap, Don't Swallow

At each layer boundary, add context to the error and preserve the original cause for downstream inspection.
- Go: `fmt.Errorf("loading user config: %w", err)` — `%w` preserves `errors.Is` / `errors.As` traversal.
- Rust: `anyhow::Context` / `.with_context(|| ...)` — attach human-readable context without losing the source.
- TypeScript: native `Error` supports a `cause` option — `new Error("fetch failed", { cause: err })`.
- Never discard the original error (`return errors.New("failed")` with no wrapping). The original context is lost forever.

## Sentinel vs Typed vs Coded Errors

Three models; choose based on callsite needs.

**Sentinel errors** (Go `io.EOF`, Rust `ErrorKind::NotFound`)
- **Use when:** callers need to branch on a single known condition without importing a type.
- **Costs:** error set is open; callers do string-equal or `errors.Is` identity checks; hard to carry payload.
- **Don't use when:** the error needs structured data (retry-after, field name, status code).

**Typed errors** (Rust `enum MyError { NotFound, Unauthorized(String) }`, Go custom struct)
- **Use when:** callers need to extract structured fields from the error.
- **Costs:** tight coupling between producer and consumer; changes to the type are breaking.
- **Don't use when:** the error crosses a service boundary — serialize to a wire format instead (see `principle-api-design#Error Shapes`).

**Coded errors** (HTTP 404, gRPC `NOT_FOUND`, application error codes)
- **Use when:** errors cross a network or process boundary; callers are in a different language or service.
- **Costs:** code registry must be maintained; codes must be documented and stable.
- **Don't use when:** all callers are in the same process — typed errors give more compile-time safety.

## Retries and Backoff

Every retry policy needs a budget, a backoff, and idempotency.
- **Exponential backoff with jitter:** `delay = min(cap, base * 2^attempt) * rand(0.5, 1.5)` — jitter prevents thundering herds.
- Only retry transient errors. Never retry permanent errors (400, `NOT_FOUND`, auth failures).
- Set a retry budget: max attempts *and* max elapsed time. Either limit should stop the loop.
- The operation must be idempotent before retrying — see `principle-api-design#Idempotency`.

## Timeouts and Deadlines

Every I/O operation must have a deadline. Unbounded waits become reliability incidents.
- Propagate the caller's deadline down through every sub-call — never create a longer deadline than the one you received.
- Distinguish timeout (local clock) from deadline (absolute wall time). Deadlines compose across service hops; timeouts do not.
- For cancellation propagation under structured concurrency, see `principle-concurrency`.
- Return a distinct error type for deadline exceeded vs connection refused — callers need to distinguish them.

## Circuit Breakers

Protect upstream services from cascading failure under sustained errors.
- **Closed:** requests flow normally; failure count tracked.
- **Open:** requests fail immediately without hitting upstream; opened when failure rate exceeds threshold.
- **Half-open:** a probe request tests recovery; success closes, failure re-opens.
- Combine with **bulkheads** — separate thread/goroutine pools or semaphores per upstream so one slow dependency does not exhaust all resources.
- Circuit breakers are overkill for single-upstream, low-traffic internal tools — add when you have observed cascading failures in production.

## Where to Handle vs Where to Bubble

Log once; at the boundary. Never log-and-return.
- Bubble errors upward until you reach the layer that can act on them (retry, convert to user response, record to audit log).
- Log at the boundary where the error is handled, not at every layer that re-wraps it. Duplicate log lines across layers obscure root cause.
- At service entry points (HTTP handler, CLI main): convert internal errors to user-facing messages; log the internal detail with request ID.
- Library code must never log — return the error. Logging policy belongs to the application.

## When Strict Error Discipline is Overkill

- Single-shot scripts with a human watching the terminal — a `log.Fatal` is fine.
- Prototypes under two weeks with no production callers.
- Single-team internal tools where the author is also the operator and on-call.

## Red Flags

| Flag | Problem |
|------|---------|
| `catch (e) {}` / `if err != nil { return nil }` | Swallowed error — failure is invisible to all callers |
| Retrying a 400 or auth error | Misclassified as transient; wastes budget, never recovers |
| No jitter on retry delay | Thundering herd when multiple callers back off in sync |
| Log + return the same error | Duplicate log lines; root-cause buried under noise |
| Library code that calls `log.Fatal` or `os.Exit` | Caller loses control of shutdown; untestable |
| `time.Sleep(30 * time.Second)` with no deadline | Goroutine/thread leak; no propagation to parent context |
