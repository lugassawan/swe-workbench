# Error Handling — Kotlin — Config Parse & Validate

## Problem

Kotlin's sealed class hierarchy gives exhaustive `when` matching without checked
exceptions. Wrapping each tier in a `ConfigError` subclass and returning
`Result<Config>` keeps the happy path readable with `getOrThrow`/`fold`, while
`runCatching` at the IO boundary converts platform exceptions into typed failures.

## Implementation

```kotlin
// file: Config.kt
import java.io.File

data class Config(val host: String, val port: Int)

sealed class ConfigError(message: String) : Exception(message) {
    class IoError(reason: String) : ConfigError("IO error: $reason")
    class ParseError(val line: Int, val reason: String)
        : ConfigError("line $line: $reason")
    class ValidationError(val field: String, val reason: String)
        : ConfigError("field '$field': $reason")
}

fun parseConfig(path: String): Result<Config> {
    val lines = runCatching { File(path).readLines() }
        .getOrElse { e -> return Result.failure(ConfigError.IoError(e.message ?: "unreadable")) }

    val kv = mutableMapOf<String, String>()
    lines.forEachIndexed { idx, raw ->
        val line = raw.trim()
        if (line.isEmpty() || line.startsWith("#")) return@forEachIndexed
        val eq = line.indexOf('=')
        if (eq < 1) return Result.failure(
            ConfigError.ParseError(idx + 1, "missing '=' separator"))
        val key = line.substring(0, eq).trim()
        if (key.isEmpty()) return Result.failure(
            ConfigError.ParseError(idx + 1, "empty key"))
        kv[key] = line.substring(eq + 1).trim()
    }

    return validateConfig(kv)
}

fun validateConfig(kv: Map<String, String>): Result<Config> {
    val host = kv["host"]?.takeIf { it.isNotEmpty() }
        ?: return Result.failure(ConfigError.ValidationError("host", "required key missing"))
    val portStr = kv["port"]
        ?: return Result.failure(ConfigError.ValidationError("port", "required key missing"))
    val port = portStr.toIntOrNull()
        ?: return Result.failure(ConfigError.ValidationError("port", "'$portStr' is not an integer"))
    if (port !in 1..65535) return Result.failure(
        ConfigError.ValidationError("port", "$port out of range 1-65535"))
    return Result.success(Config(host, port))
}
```

```kotlin
// file: Main.kt
fun main() {
    parseConfig("app.conf").fold(
        onSuccess = { cfg -> println("host=${cfg.host} port=${cfg.port}") },
        onFailure = { err ->
            when (err) {
                is ConfigError.IoError         -> System.err.println("IO error: ${err.message}")
                is ConfigError.ParseError      -> System.err.println("Parse error line ${err.line}: ${err.reason}")
                is ConfigError.ValidationError -> System.err.println("Validation error '${err.field}': ${err.reason}")
                else                           -> System.err.println("Unexpected: ${err.message}")
            }
        }
    )
}
```

## Common Mistake

Catching all exceptions at the parse level and returning an empty `Config` — type safety is lost and the caller has no way to detect or diagnose the failure.

```kotlin
} catch (e: Exception) {    // ✗ catches IO, parse, and validation alike
    return Result.success(Config("", 0))  // ✗ zero Config masks every failure tier
}
```
