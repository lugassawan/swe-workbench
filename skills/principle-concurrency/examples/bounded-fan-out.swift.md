# Bounded Fan-out — Swift — withThrowingTaskGroup drain-as-you-add

## Problem

Swift structured concurrency has no built-in concurrency cap on `TaskGroup`. The
drain-as-you-add pattern enforces K=5 by adding a new child task only after an inflight
task completes: once `active == K`, call `next()` to drain one result before adding the
next. Results are stored in a dictionary keyed by index and converted to an ordered array
at the end, preserving original order despite out-of-order completion.

## Implementation

```swift
// file: bounded-fan-out.swift
import Foundation

func fetch(id: String) async throws -> String {
    try await Task.sleep(nanoseconds: 10_000_000)
    return "result-\(id)"
}

func boundedFanOut(ids: [String], limit: Int) async throws -> [String] {
    var results = [Int: String]()
    var active = 0

    try await withThrowingTaskGroup(of: (Int, String).self) { group in
        for (i, id) in ids.enumerated() {
            if active == limit {
                // Drain one before adding the next to stay at limit.
                if let (idx, val) = try await group.next() {
                    results[idx] = val
                    active -= 1
                }
            }
            group.addTask { (i, try await fetch(id: id)) }
            active += 1
        }
        // Drain remainder.
        for try await (idx, val) in group {
            results[idx] = val
        }
    }
    return (0..<ids.count).map { results[$0]! }
}

// Usage
Task {
    let ids = ["a", "b", "c", "d", "e", "f", "g", "h"]
    let out = try await boundedFanOut(ids: ids, limit: 5)
    print(out)
}
```

## Common Mistake

Adding all tasks at once inside `withThrowingTaskGroup` with no drain creates unbounded concurrency.

```swift
// ✗ all N tasks added immediately — no cap on concurrent work
func badFanOut(ids: [String]) async throws -> [String] {
    var results = [Int: String]()
    try await withThrowingTaskGroup(of: (Int, String).self) { group in
        for (i, id) in ids.enumerated() {
            group.addTask { (i, try await fetch(id: id)) } // ✗ unbounded
        }
        for try await (idx, val) in group { results[idx] = val }
    }
    return (0..<ids.count).map { results[$0]! }
}
```
