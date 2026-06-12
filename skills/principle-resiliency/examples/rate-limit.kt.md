# Resiliency — Kotlin — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```kotlin
// file: TokenBucket.kt
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock
import kotlin.math.min

class TokenBucket(
    private val capacity: Double,
    refillPerSecond: Double,
) {
    private val refillPerMs = refillPerSecond / 1000.0
    private var tokens = capacity
    private var lastRefillMs = System.currentTimeMillis()
    private val lock = ReentrantLock()

    fun tryAcquire(): Boolean = lock.withLock {
        val now = System.currentTimeMillis()
        tokens = min(capacity, tokens + (now - lastRefillMs) * refillPerMs)
        lastRefillMs = now
        if (tokens >= 1) { tokens--; true } else false
    }
}
```

```kotlin
// file: main.kt
import kotlin.random.Random

fun <T> callWithRateLimit(bucket: TokenBucket, operation: () -> T, maxAttempts: Int = 5): T {
    repeat(maxAttempts) { attempt ->
        if (bucket.tryAcquire()) return operation()
        // Jitter prevents synchronized retries (thundering herd).
        val backoff = (1L shl attempt) * (0.5 + Random.nextDouble())
        Thread.sleep(backoff.toLong())
    }
    throw RuntimeException("rate limit exhausted")
}

fun main() {
    val bucket = TokenBucket(capacity = 3.0, refillPerSecond = 1.0)
    for (i in 0 until 5) {
        try {
            println(callWithRateLimit(bucket) { "ok-$i" })
        } catch (e: RuntimeException) {
            println("rejected")
        }
    }
}
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```kotlin
class FixedWindowUnsafe(private val limit: Int, private val windowMs: Long) {
    private var count = 0
    private var windowStart = System.currentTimeMillis()

    fun tryAcquire(): Boolean {
        val now = System.currentTimeMillis()
        if (now - windowStart >= windowMs) {
            count = 0              // ✗ hard reset enables boundary burst
            windowStart = now
        }
        return if (count < limit) { count++; true } else false
    }
}
```
