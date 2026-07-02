# Error Handling — Swift — Config Parse & Validate

## Problem

Swift's `throws` + typed `enum Error` make every failure site explicit in the
function signature. A `ConfigError` enum with associated values for IO, parse, and
validation lets callers `catch` each case individually in a `do/catch` block, while
`try` propagation keeps the call chain concise without hiding which tier failed.

## Implementation

```swift
// file: config.swift
import Foundation

enum ConfigError: Error {
    case io(Error)
    case parse(line: Int, reason: String)
    case validation(field: String, reason: String)
}

struct Config { let host: String; let port: Int }

func parseConfig(path: String) throws -> Config {
    let text: String
    do {
        text = try String(contentsOfFile: path, encoding: .utf8)
    } catch {
        throw ConfigError.io(error)
    }

    var kv = [String: String]()
    let lines = text.components(separatedBy: "\n")
    for (idx, raw) in lines.enumerated() {
        let line = raw.trimmingCharacters(in: .whitespaces)
        if line.isEmpty || line.hasPrefix("#") { continue }
        let parts = line.split(separator: "=", maxSplits: 1)
        guard parts.count == 2 else {
            throw ConfigError.parse(line: idx + 1, reason: "missing '=' separator")
        }
        let key = parts[0].trimmingCharacters(in: .whitespaces)
        guard !key.isEmpty else {
            throw ConfigError.parse(line: idx + 1, reason: "empty key")
        }
        kv[key] = parts[1].trimmingCharacters(in: .whitespaces)
    }

    return try validateConfig(kv)
}

func validateConfig(_ kv: [String: String]) throws -> Config {
    guard let host = kv["host"], !host.isEmpty else {
        throw ConfigError.validation(field: "host", reason: "required key missing")
    }
    guard let portStr = kv["port"] else {
        throw ConfigError.validation(field: "port", reason: "required key missing")
    }
    guard let port = Int(portStr) else {
        throw ConfigError.validation(field: "port", reason: "'\(portStr)' is not an integer")
    }
    guard (1...65535).contains(port) else {
        throw ConfigError.validation(field: "port", reason: "\(port) out of range 1-65535")
    }
    return Config(host: host, port: port)
}
```

```swift
// file: main.swift
do {
    let cfg = try parseConfig(path: "app.conf")
    print("host=\(cfg.host) port=\(cfg.port)")
} catch ConfigError.io(let e) {
    fputs("IO error: \(e.localizedDescription)\n", stderr)
} catch ConfigError.parse(let line, let reason) {
    fputs("Parse error line \(line): \(reason)\n", stderr)
} catch ConfigError.validation(let field, let reason) {
    fputs("Validation error '\(field)': \(reason)\n", stderr)
}
```

## Common Mistake

Using `try?` — the typed `ConfigError` is discarded and the caller receives `nil` with no information about which tier failed or why.

```swift
let cfg = try? parseConfig(path: "app.conf")  // ✗ all three error cases collapsed to nil
// caller cannot distinguish missing file from invalid port — no diagnostic available
```
