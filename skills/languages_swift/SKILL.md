name: languages-swift
description: Swift best practices including async/await, actors, protocol-oriented design, and safe data handling.
triggers:
  - .swift
  - Package.swift
  - actors
  - async/await
  - Result builders
  - optionals
  - protocols
---
## Swift Best Practices
Swift Fundamentals
Prefer structs over classes

Use protocol-oriented programming

Keep types small and focused

Optionals
Avoid force unwrap !

Use if let, guard let

Handle nil safely

Concurrency
Use async/await

Use actors for shared state

Avoid manual threading

Error Handling
Use throws and do-catch

Use Result where appropriate

Memory Management
Avoid retain cycles (weak, unowned)

Be careful with closures

SwiftUI / Builders
Use Result builders for UI

Keep views declarative and simple

Packages
Use Swift Package Manager (Package.swift)

Keep modules small

Protocols
Use protocols for abstraction

Prefer composition over inheritance

Testing
Use XCTest

Focus on behavior and edge cases

