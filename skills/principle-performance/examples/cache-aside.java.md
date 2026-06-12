# Caching — Java — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```java
// file: CacheAside.java
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.*;
import java.util.function.Function;

public class CacheAside<V> {
    private record Entry<V>(V value, Instant expiresAt) {}

    private final ConcurrentHashMap<String, Entry<V>> store = new ConcurrentHashMap<>();
    // computeIfAbsent on ConcurrentHashMap serialises concurrent calls for the same key,
    // providing single-flight semantics without an explicit per-key lock map.
    private final Duration ttl;
    private final Function<String, V> loader;

    public CacheAside(Duration ttl, Function<String, V> loader) {
        this.ttl = ttl;
        this.loader = loader;
    }

    public V get(String key) {
        Entry<V> entry = store.get(key);
        if (entry != null && Instant.now().isBefore(entry.expiresAt())) {
            return entry.value();
        }
        // compute is atomic per-key (bin-level lock in ConcurrentHashMap since Java 8):
        // eviction of a stale entry and recomputation happen as a single step, so only
        // one thread calls loader for a given key at a time.
        return store.compute(key, (k, existing) -> {
            if (existing != null && Instant.now().isBefore(existing.expiresAt())) {
                return existing; // another thread already refreshed it
            }
            V value = loader.apply(k);
            return new Entry<>(value, Instant.now().plus(ttl));
        }).value();
    }
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```java
// ✗ check-then-act without synchronisation — race allows multiple threads to call loader
Entry<V> entry = store.get(key);
if (entry == null || Instant.now().isAfter(entry.expiresAt())) {
    V value = loader.apply(key); // ✗ multiple threads call loader concurrently
    store.put(key, new Entry<>(value, Instant.now().plus(ttl)));
}
```
