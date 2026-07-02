# Resiliency — Swift — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```swift
// file: IdempotencyStore.swift
import Foundation

actor IdempotencyStore<T> {
    private enum Entry {
        case pending
        case completed(T)
    }

    private var store: [String: Entry] = [:]

    func execute(key: String, operation: () async throws -> T) async throws -> T {
        switch store[key] {
        case .completed(let result): return result
        case .pending: throw IdempotencyError.inFlight(key)
        case nil: break
        }

        // Reserve BEFORE executing — concurrent retry sees .pending and stops.
        store[key] = .pending

        do {
            let result = try await operation()
            store[key] = .completed(result)
            return result
        } catch {
            store.removeValue(forKey: key)  // release — allows retry with same key
            throw error
        }
    }
}

enum IdempotencyError: Error {
    case inFlight(String)
}
```

```swift
// file: main.swift
import Foundation

let store = IdempotencyStore<[String: Any]>()
var calls = 0

func charge() async -> [String: Any] {
    calls += 1
    return ["charge_id": "ch_123", "amount": 100]
}

let key = "order-abc-attempt-1"
let r1 = try await store.execute(key: key) { await charge() }
let r2 = try await store.execute(key: key) { await charge() } // duplicate — cached

assert(r1["charge_id"] as? String == r2["charge_id"] as? String)
assert(calls == 1, "charge executed \(calls) times — expected 1")
print("charge_id=\(r1["charge_id"] as? String ?? "?") calls=\(calls)")
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```swift
func executeUnsafe(key: String, op: () async -> T) async -> T {
    let result = await op()     // ✗ side effect runs first
    store[key] = result         // ✗ key recorded after — concurrent retry double-charges
    return result
}
```
