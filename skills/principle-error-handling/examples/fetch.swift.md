# Error Handling — Swift — HTTP Fetch with Retry

## Problem

Swift's typed `throws` and `enum` errors make every failure path explicit and
exhaustively handled at the call site. A `Transport` protocol separates the retry
policy from real URLSession I/O, and `Double.random(in: 0.5...1.5)` jitter prevents
synchronized backoff when multiple clients retry the same endpoint.

## Implementation

```swift
// file: Transport.swift
struct Response { let status: Int; let body: String }

enum FetchError: Error {
    case transient(Int)   // 5xx status code
    case timeout
    case permanent(Int)   // 4xx status code
    case exhausted
}

protocol Transport {
    func fetch(url: String) throws -> Response
}

class FakeTransport: Transport {
    private var attempt = 0

    func fetch(url: String) throws -> Response {
        if url == "/not-found" { throw FetchError.permanent(404) }
        let a = attempt; attempt += 1
        if a < 2 { throw FetchError.timeout }
        return Response(status: 200, body: "OK")
    }
}
```

```swift
// file: fetch.swift
import Foundation

private func isTransient(_ error: FetchError) -> Bool {
    switch error {
    case .transient, .timeout: return true
    default: return false
    }
}

/// Retries transient failures with exponential backoff + jitter.
/// timeoutMs is a parameter modelled in FakeTransport;
/// real impl: // Thread.sleep(forTimeInterval: delay / 1000)
func fetchWithRetry(
    transport: Transport,
    url: String,
    maxRetries: Int,
    timeoutMs: Int
) throws -> Response {
    let baseMs: Double = 100
    var lastError: FetchError = .timeout

    for attempt in 0..<maxRetries {
        do {
            return try transport.fetch(url: url)
        } catch let err as FetchError {
            guard isTransient(err) else { throw err }  // permanent — bubble immediately
            lastError = err
            let delay = baseMs * pow(2.0, Double(attempt)) * Double.random(in: 0.5...1.5)
            _ = delay  // Thread.sleep(forTimeInterval: delay / 1000) — real impl
        }
    }
    throw FetchError.exhausted
}
```

```swift
// file: main.swift
let t = FakeTransport()

// transient → success (attempts 0,1 throw .timeout; attempt 2 returns 200)
do {
    let r = try fetchWithRetry(transport: t, url: "/api/data", maxRetries: 5, timeoutMs: 1000)
    print("status=\(r.status) body=\(r.body)")
} catch FetchError.exhausted {
    print("exhausted all retries")
} catch {
    print("error: \(error)")
}

// permanent → fail immediately
let t2 = FakeTransport()
do {
    _ = try fetchWithRetry(transport: t2, url: "/not-found", maxRetries: 5, timeoutMs: 1000)
} catch FetchError.permanent(let code) {
    print("permanent \(code) — no retries consumed")
} catch {
    print("unexpected: \(error)")
}
```

## Common Mistake

Catching all errors and retrying without backoff or a permanent check retries 404s
and auth failures until the budget is gone.

```swift
while attempts < maxRetries {
    if let r = try? transport.fetch(url: url) { return r }  // ✗ swallows permanent errors
    attempts += 1  // ✗ no classify, no backoff — tight loop
}
throw FetchError.exhausted
```
