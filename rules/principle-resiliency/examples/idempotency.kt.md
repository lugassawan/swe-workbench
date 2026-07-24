# Resiliency — Kotlin — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```kotlin
// file: IdempotencyStore.kt
import java.util.concurrent.ConcurrentHashMap

class IdempotencyStore<T> {
    private enum class Status { PENDING, COMPLETED }
    private data class Entry<T>(val status: Status, val result: T? = null)

    private val store = ConcurrentHashMap<String, Entry<T>>()

    fun execute(key: String, operation: () -> T): T {
        // Reserve BEFORE executing — concurrent retry sees PENDING and stops.
        val existing = store.putIfAbsent(key, Entry(Status.PENDING))
        if (existing != null) {
            @Suppress("UNCHECKED_CAST")
            if (existing.status == Status.COMPLETED) return existing.result as T
            throw IllegalStateException("key '$key' already in-flight")
        }

        try {
            val result = operation()
            store[key] = Entry(Status.COMPLETED, result)
            return result
        } catch (e: Exception) {
            store.remove(key)  // release — allows retry with same key
            throw e
        }
    }
}
```

```kotlin
// file: main.kt
fun main() {
    val store = IdempotencyStore<Map<String, Any>>()
    var calls = 0

    val charge = {
        calls++
        mapOf("charge_id" to "ch_123", "amount" to 100)
    }

    val key = "order-abc-attempt-1"
    val r1 = store.execute(key, charge)
    val r2 = store.execute(key, charge) // duplicate — returns cached result

    check(r1 == r2)
    check(calls == 1) { "charge executed $calls times — expected 1" }
    println("charge_id=${r1["charge_id"]} calls=$calls") // charge_id=ch_123 calls=1
}
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```kotlin
fun executeUnsafe(key: String, op: () -> T): T {
    val result = op()          // ✗ side effect runs first
    store[key] = result        // ✗ key recorded after — concurrent retry double-charges
    return result
}
```
