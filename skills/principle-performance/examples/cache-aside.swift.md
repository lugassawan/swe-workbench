# Caching — Swift — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```swift
// file: CacheAside.swift
import Foundation

private struct Entry<V> {
    let value: V
    let expiresAt: Date
}

/// Cache-aside using Swift actor isolation for single-flight on cold/expired keys.
/// Concurrent `get` calls for the same key share one in-flight `Task`; the loader runs exactly once.
actor CacheAside<V: Sendable> {
    private var store: [String: Entry<V>] = [:]
    private var inflight: [String: Task<V, Error>] = [:]
    private let ttl: TimeInterval
    private let loader: @Sendable (String) async throws -> V

    init(ttl: TimeInterval, loader: @Sendable @escaping (String) async throws -> V) {
        self.ttl = ttl
        self.loader = loader
    }

    func get(_ key: String) async throws -> V {
        if let entry = store[key], Date.now < entry.expiresAt {
            return entry.value
        }
        // Single-flight via actor isolation: reuse an in-progress Task for the same key.
        if let task = inflight[key] {
            return try await task.value
        }
        let task = Task { try await self.loader(key) }
        inflight[key] = task
        do {
            let value = try await task.value
            store[key] = Entry(value: value, expiresAt: Date.now.addingTimeInterval(ttl))
            inflight.removeValue(forKey: key)
            return value
        } catch {
            inflight.removeValue(forKey: key)
            throw error
        }
    }
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```swift
// ✗ no in-flight guard — each concurrent call spawns a separate Task and hits the origin
if let entry = store[key], Date.now < entry.expiresAt { return entry.value }
// ✗ two callers missing the same key both create a Task and call loader independently
let value = try await loader(key)
store[key] = Entry(value: value, expiresAt: Date.now.addingTimeInterval(ttl))
return value
```
