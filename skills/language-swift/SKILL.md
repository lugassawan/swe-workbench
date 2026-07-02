---
name: language-swift
description: Swift idioms — optionals, value types, actors, async/await, protocols, and Result builders. Auto-load when working with .swift files, Package.swift, or when the user mentions Swift, SwiftUI, actors, async/await, Sendable, Result builders, or Swift Package Manager.
---

# Swift

## Optionals
- `?` makes absence explicit in the type — `String?` vs `String`.
- `if let` / `guard let` unwrap safely. `guard` exits scope immediately — prefer it for preconditions.
- `??` provides a default for `nil`. **Never force-unwrap (`!`) in production** unless the nil case is a programmer error that should crash loudly.

```swift
guard let email = user.email else { return }
let display = nickname ?? username
```

## Value vs reference types
- Default to `struct` — value semantics, copy-on-write, no shared-mutation bugs.
- Use `class` only when identity matters (reference equality, inheritance), or when Objective-C interop requires it.
- Use `actor` to encapsulate mutable state that must be safe to access from multiple async tasks.

```swift
actor Counter {
    private var count = 0
    func increment() { count += 1 }
    func value() -> Int { count }
}
```

## Protocols and protocol-oriented design
- Model capabilities as protocols, not class hierarchies. `Hashable`, `Codable`, `Identifiable` are the idiom.
- Extension methods add behavior without subclassing.
- `some Protocol` (opaque return type) keeps the concrete type private while preserving type identity.
- `any Protocol` (existential) erases the type — use only when you need a heterogeneous collection.

```swift
protocol Fetchable { associatedtype Item; func fetch(id: String) async throws -> Item }
func loadFirst<F: Fetchable>(from source: F) async throws -> F.Item { try await source.fetch(id: "1") }
```

## Concurrency — async/await
- `async`/`await` replaces completion handlers. Mark any function that suspends as `async`.
- `async let` for structured concurrency — values resolve when awaited, not when declared.
- `withTaskGroup` for dynamic fan-out over a collection.
- `Task.checkCancellation()` in long loops; cancellation is cooperative.

```swift
async let user  = fetchUser(id)
async let prefs = fetchPreferences(id)
let dashboard = try await Dashboard(user: user, prefs: prefs)
```

- Mark types that cross concurrency boundaries as `Sendable` (or use `@unchecked Sendable` with a documented invariant).

## Errors — throws and Result
- `throws` + `try`/`catch` for recoverable domain errors. Define errors as `enum` conforming to `Error`.
- `try?` silences an error and returns `nil` — acceptable for optional lookups, not for error paths.
- `try!` crashes on failure — reserved for assets that ship with the binary.
- `Result<Success, Failure>` at async boundaries where completion handlers are still used.

```swift
enum NetworkError: Error { case timeout, unauthorized, badResponse(Int) }

func load(url: URL) async throws -> Data {
    let (data, response) = try await URLSession.shared.data(from: url)
    guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
        throw NetworkError.badResponse((response as? HTTPURLResponse)?.statusCode ?? 0)
    }
    return data
}
```

## Result builders
- `@resultBuilder` enables declarative DSLs — SwiftUI's `@ViewBuilder` is the canonical example.
- Use when you need a list of same-typed values built from heterogeneous expressions.
- Avoid for general-purpose construction where a plain array initialiser suffices.

## Memory — retain cycles
- Value types (`struct`, `enum`) have no retain cycles.
- In escaping closures that capture `self`, use `[weak self]` + `guard let self` to break cycles.
- `[unowned self]` only when you can prove `self` outlives the closure — a narrow case.

```swift
button.onTap = { [weak self] in
    guard let self else { return }
    self.handleTap()
}
```

## Packaging — Swift Package Manager
- `Package.swift` is the modern standard. Avoid CocoaPods / Carthage in new projects.
- One target per logical module. Keep `Sources/` layout mirroring the module name.
- Pin dependencies via `Package.resolved` in version control for reproducible builds.

## Tooling
- **Format:** `swiftformat .` (nicklockwood/SwiftFormat) **or** `swift-format format -i -r .` (Apple — incompatible config; pick one per project)
- **Lint:** `swiftlint lint`
- **Test:** `swift test` (see Testing below)

## Testing
- XCTest: `XCTAssertEqual`, `XCTUnwrap` (throws if nil, cleaner than force-unwrap in tests).
- Swift Testing (`@Test`, `#expect`) for new projects on Swift 6.0+ (Xcode 16+).
- Async tests: `await fulfillment(of: [expectation], timeout: 1)` in XCTest; `@Test` supports `async` natively.

```swift
@Test func orderTotalExcludesCancelledLines() async throws {
    let order = try await OrderService.fetch("ord-1")
    #expect(order.total > 0)
}
```

## Avoid
- Force-unwrap (`!`) outside test code or provably non-nil asset access.
- Escaping closures capturing `self` without `[weak self]` when a retain cycle is possible.
- `class` where `struct` + `actor` would give safer semantics.
- `NSObject` inheritance unless Objective-C interop requires it.
- Mixing `async/await` with callback-based APIs — wrap callbacks in `withCheckedThrowingContinuation`.
