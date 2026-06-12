# Resiliency — Swift — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```swift
// file: TokenBucket.swift
import Foundation

actor TokenBucket {
    private let capacity: Double
    private let refillPerMs: Double
    private var tokens: Double
    private var lastRefill: Date

    init(capacity: Double, refillPerSecond: Double) {
        self.capacity = capacity
        self.refillPerMs = refillPerSecond / 1000.0
        self.tokens = capacity
        self.lastRefill = Date()
    }

    func tryAcquire() -> Bool {
        let now = Date()
        let elapsedMs = now.timeIntervalSince(lastRefill) * 1000
        tokens = min(capacity, tokens + elapsedMs * refillPerMs)
        lastRefill = now
        if tokens >= 1 {
            tokens -= 1
            return true
        }
        return false
    }
}
```

```swift
// file: main.swift
import Foundation

let bucket = TokenBucket(capacity: 3, refillPerSecond: 1.0)

func callWithRateLimit<T>(
    _ op: () async -> T,
    maxAttempts: Int = 5
) async throws -> T {
    for attempt in 0..<maxAttempts {
        if await bucket.tryAcquire() { return await op() }
        // Jitter prevents synchronized retries (thundering herd).
        let baseMs = UInt64(1 << attempt)
        let jitterMs = baseMs / 2 + UInt64.random(in: 0...(baseMs / 2))
        try await Task.sleep(nanoseconds: jitterMs * 1_000_000)
    }
    throw RateLimitError.exhausted
}

enum RateLimitError: Error { case exhausted }

for i in 0..<5 {
    do {
        let result = try await callWithRateLimit { "ok-\(i)" }
        print(result)
    } catch {
        print("rejected")
    }
}
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```swift
class FixedWindowUnsafe {
    private let limit: Int
    private let windowMs: TimeInterval
    private var count = 0
    private var windowStart = Date()

    init(limit: Int, windowMs: TimeInterval) {
        self.limit = limit; self.windowMs = windowMs
    }

    func tryAcquire() -> Bool {
        let now = Date()
        if now.timeIntervalSince(windowStart) * 1000 >= windowMs {
            count = 0              // ✗ hard reset enables boundary burst
            windowStart = now
        }
        guard count < limit else { return false }
        count += 1; return true
    }
}
```
