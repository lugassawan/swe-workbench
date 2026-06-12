# Caching — Kotlin — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```kotlin
// file: CacheAside.kt
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Duration
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap

private data class Entry<V>(val value: V, val expiresAt: Instant)

class CacheAside<V>(
    private val ttl: Duration,
    private val loader: suspend (String) -> V,
) {
    private val store = ConcurrentHashMap<String, Entry<V>>()
    // Per-key Mutex: only one coroutine recomputes a cold/expired entry.
    // computeIfAbsent is atomic per-key; getOrPut is NOT — two coroutines could get different instances.
    // Note: kotlinx Mutex is NOT reentrant — calling withLock inside withLock on the same mutex deadlocks.
    private val locks = ConcurrentHashMap<String, Mutex>()

    suspend fun get(key: String): V {
        store[key]?.let { if (Instant.now().isBefore(it.expiresAt)) return it.value }

        val mutex = locks.computeIfAbsent(key) { Mutex() }
        return mutex.withLock {
            // Re-check after acquiring: a concurrent caller may have already populated the entry.
            store[key]?.let { if (Instant.now().isBefore(it.expiresAt)) return it.value }

            val value = loader(key)
            store[key] = Entry(value, Instant.now().plus(ttl))
            value
        }
    }
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```kotlin
// ✗ no mutex — concurrent coroutines all miss and call loader simultaneously
store[key]?.let { if (Instant.now().isBefore(it.expiresAt)) return it.value }
val value = loader(key) // ✗ thundering herd on a cold/expired key
store[key] = Entry(value, Instant.now().plus(ttl))
return value
```
