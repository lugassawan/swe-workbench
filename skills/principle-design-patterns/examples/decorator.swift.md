# Decorator — Swift — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior without modifying `HttpFetcher`.
Swift's `protocol Fetcher` lets `RetryFetcher` and `LoggingFetcher` each wrap any
`Fetcher` conformance and delegate to it, adding a single concern. They compose in
any order — the core class is never changed.

## Implementation

```swift
// file: Fetcher.swift
import Foundation

protocol Fetcher {
    func fetch(url: String) throws -> String
}

struct HttpFetcher: Fetcher {
    func fetch(url: String) throws -> String {
        guard let u = URL(string: url) else { throw URLError(.badURL) }
        var result: Result<Data, Error>?
        let sem = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: u) { data, _, err in
            result = data.map { .success($0) } ?? .failure(err ?? URLError(.unknown))
            sem.signal()
        }.resume()
        sem.wait()
        return String(decoding: try result!.get(), as: UTF8.self)
    }
}

struct RetryFetcher: Fetcher {
    let inner: any Fetcher
    let retries: Int

    func fetch(url: String) throws -> String {
        var lastError: Error?
        for _ in 0...retries {
            do { return try inner.fetch(url: url) }
            catch { lastError = error }
        }
        throw lastError!
    }
}

struct LoggingFetcher: Fetcher {
    let inner: any Fetcher

    func fetch(url: String) throws -> String {
        print("[fetch] GET \(url)")
        do {
            let result = try inner.fetch(url: url)
            print("[fetch] OK  \(url)")
            return result
        } catch {
            print("[fetch] ERR \(url): \(error)")
            throw error
        }
    }
}
```

```swift
// file: main.swift
let fetcher: any Fetcher = LoggingFetcher(
    inner: RetryFetcher(inner: HttpFetcher(), retries: 3)
)

do {
    let body = try fetcher.fetch(url: "https://example.com/api/data")
    print(body)
} catch {
    print("error:", error)
}
```

## Common Mistake

Subclassing `HttpFetcher` with a combined class — behaviors are inseparable and every
new combination demands a new subclass.

```swift
// ✗ subclass explosion — retry + logging fused into one class
class HttpFetcherBase {                          // must be a class for subclassing
    func fetch(url: String) throws -> String { /* core HTTP fetch */ }
}
class RetryLoggingFetcher: HttpFetcherBase {     // ✗ combined into one subclass
    override func fetch(url: String) throws -> String {
        print("[fetch] GET \(url)")              // ✗ retry cannot be used without logging
        for _ in 0..<3 {
            if let r = try? super.fetch(url: url) { return r }
        }
        throw URLError(.cannotConnectToHost)
    }
}
// class CachingRetryFetcher: HttpFetcherBase { ... } // ✗ N behaviors → N² subclasses
```
