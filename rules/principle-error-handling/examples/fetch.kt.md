# Error Handling — Kotlin — HTTP Fetch with Retry

## Problem

Kotlin's sealed classes turn error classification into an exhaustive `when` expression
that the compiler enforces. A `Transport` interface isolates the retry policy from real
I/O, and `Random.nextFloat()` jitter prevents synchronized backoff spikes when multiple
clients retry simultaneously.

## Implementation

```kotlin
// file: transport.kt
data class Response(val status: Int, val body: String)

sealed class FetchError : Exception() {
    data class Transient(val statusCode: Int) : FetchError()
    object Timeout : FetchError()
    data class Permanent(val statusCode: Int) : FetchError()
    object Exhausted : FetchError()
}

interface Transport {
    fun fetch(url: String): Result<Response>
}

class FakeTransport : Transport {
    private var attempt = 0

    override fun fetch(url: String): Result<Response> {
        if (url == "/not-found") return Result.failure(FetchError.Permanent(404))
        val a = attempt++
        return if (a < 2) Result.failure(FetchError.Timeout)
               else Result.success(Response(200, "OK"))
    }
}
```

```kotlin
// file: fetch.kt
import kotlin.math.pow
import kotlin.random.Random

private fun isTransient(error: Throwable): Boolean = when (error) {
    is FetchError.Transient, is FetchError.Timeout -> true
    else -> false
}

/**
 * Retries transient failures with exponential backoff + jitter.
 * timeoutMs is modelled in FakeTransport; real impl uses OkHttp callTimeout.
 */
fun fetchWithRetry(
    transport: Transport,
    url: String,
    maxRetries: Int,
    timeoutMs: Int,
): Result<Response> {
    val baseMs = 100.0
    for (attempt in 0 until maxRetries) {
        val result = transport.fetch(url)
        if (result.isSuccess) return result
        val err = result.exceptionOrNull() ?: return result  // isSuccess path already returned
        if (!isTransient(err)) return result        // permanent — bubble immediately
        val delay = baseMs * 2.0.pow(attempt) * (Random.nextFloat() * 1.0f + 0.5f)
        @Suppress("UNUSED_VARIABLE") val d = delay // Thread.sleep(delay.toLong()) — real impl
    }
    return Result.failure(FetchError.Exhausted)
}
```

```kotlin
// file: main.kt
fun main() {
    val t = FakeTransport()

    // transient → success (attempts 0,1 timeout; attempt 2 returns 200)
    fetchWithRetry(t, "/api/data", maxRetries = 5, timeoutMs = 1000)
        .onSuccess { println("status=${it.status} body=${it.body}") }
        .onFailure { println("error: $it") }

    // permanent → fail immediately (no retries consumed)
    val t2 = FakeTransport()
    fetchWithRetry(t2, "/not-found", maxRetries = 5, timeoutMs = 1000)
        .onSuccess { println("unexpected ok: ${it.status}") }
        .onFailure { err ->
            when (err) {
                is FetchError.Permanent -> println("permanent ${err.statusCode} — no retries")
                is FetchError.Exhausted -> println("exhausted")
                else -> println("other: $err")
            }
        }
}
```

## Common Mistake

Retrying all failures including permanent ones with no delay discards the classify step
and floods the server with pointless requests on unrecoverable errors.

```kotlin
for (attempt in 0 until maxRetries) {
    val r = transport.fetch(url)
    if (r.isSuccess) return r  // ✗ retries Permanent(404) — no classify
    // ✗ no backoff — tight loop
}
```
