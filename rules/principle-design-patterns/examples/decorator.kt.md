# Decorator — Kotlin — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior without those concerns being baked
into the fetch function. Kotlin's higher-order functions make the Decorator pattern
lightweight: `withRetry` and `withLogging` each accept a `(String) -> String` function
and return a new one, composable in any order with no class hierarchy.

## Implementation

```kotlin
// file: fetcher.kt
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse

private val client = HttpClient.newHttpClient()

fun httpFetch(url: String): String {
    val req = HttpRequest.newBuilder(URI.create(url)).GET().build()
    return client.send(req, HttpResponse.BodyHandlers.ofString()).body()
}

fun withRetry(fn: (String) -> String, n: Int): (String) -> String = { url ->
    var lastErr: Throwable? = null
    var result: String? = null
    for (i in 0..n) {
        runCatching { fn(url) }
            .onSuccess { result = it }
            .onFailure { lastErr = it }
        if (result != null) break
    }
    result ?: throw lastErr!!
}

fun withLogging(fn: (String) -> String): (String) -> String = { url ->
    println("[fetch] GET $url")
    runCatching { fn(url) }
        .onSuccess { println("[fetch] OK  $url") }
        .onFailure { println("[fetch] ERR $url: ${it.message}") }
        .getOrThrow()
}
```

```kotlin
// file: main.kt
fun main() {
    val fetch = withLogging(withRetry(::httpFetch, 3))
    println(fetch("https://example.com/api/data"))
    // [fetch] GET https://example.com/api/data
    // [fetch] OK  https://example.com/api/data
}
```

## Common Mistake

Fusing retry and logging into a single combined function — both behaviors are
inseparable, and adding caching requires yet another variant for each existing combo.

```kotlin
// ✗ subclass explosion — retry and logging fused; cannot be used independently
fun retryLoggingFetch(url: String): String {      // ✗ both behaviors locked together
    println("[fetch] GET $url")                    // ✗ cannot retry without logging
    repeat(3) {
        runCatching { httpFetch(url) }.onSuccess { return it }
    }
    throw IllegalStateException("all retries failed")
    // ✗ adding caching needs retryLoggingCachingFetch, cachingFetch, retryFetch, …
}
```
