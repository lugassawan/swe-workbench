# Bounded Fan-out — Kotlin — coroutines + Semaphore

## Problem

Fetch N items concurrently with Kotlin coroutines, capping inflight work at K=5 using
`kotlinx.coroutines.sync.Semaphore`. Each `async` coroutine acquires a permit before
calling `fetch` and releases it automatically via `withPermit`. `awaitAll()` on the
deferred list collects results in original order without extra sorting.

## Implementation

```kotlin
// file: bounded-fan-out.kt
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit

suspend fun fetch(id: String): String {
    delay(10)
    return "result-$id"
}

fun main() = runBlocking {
    val ids = listOf("a", "b", "c", "d", "e", "f", "g", "h")
    val K = 5
    val sem = Semaphore(K)

    val results: List<String> = coroutineScope {
        ids.map { id ->
            async {
                sem.withPermit { fetch(id) } // blocks until a permit is available
            }
        }.awaitAll() // order matches ids list
    }
    println(results)
}
```

## Common Mistake

Launching all coroutines with `async` and no semaphore removes the concurrency cap.

```kotlin
// ✗ all N coroutines are launched simultaneously — no cap
val badResults = coroutineScope {
    ids.map { id ->
        async { fetch(id) } // ✗ unbounded — no Semaphore
    }.awaitAll()
}
```
