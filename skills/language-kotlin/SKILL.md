---
name: language-kotlin
description: Kotlin idioms — null safety, coroutines, sealed interfaces, scope functions, and Flow. Auto-load when working with .kt files, build.gradle.kts, or when the user mentions Kotlin, coroutines, suspend, StateFlow, sealed interface, or Kotlin DSL.
---

# Kotlin

## Null safety
- `?` makes nullability explicit in the type — `String?` vs `String`.
- Safe-call `?.` returns null instead of throwing. Elvis `?:` provides a default.
- **Never use `!!` in production code** — it is a promise you will never break that can't be verified.

```kotlin
val length = name?.trim()?.length ?: 0
user?.email?.let { send(it) }   // null-guard + scoping
```

## Data classes and sealed interfaces
- `data class` for value containers: auto-generates `equals`, `hashCode`, `toString`, `copy`, and destructuring.
- `sealed interface` closes a hierarchy and enables exhaustive `when` without an `else` branch.

```kotlin
sealed interface Result<out T>
data class Success<T>(val value: T) : Result<T>
data class Failure(val error: Throwable) : Result<Nothing>

fun handle(r: Result<User>) = when (r) {
    is Success -> show(r.value)
    is Failure -> log(r.error)
}
```

## Coroutines — structured concurrency
- `suspend` functions must be called from a coroutine or another `suspend` function.
- Use `coroutineScope { }` for fan-out — child coroutines are cancelled if one fails.
- `withContext(Dispatchers.IO)` for blocking IO; never block inside `Dispatchers.Default`.

```kotlin
suspend fun fetchDashboard(id: String): Dashboard = coroutineScope {
    val user   = async { fetchUser(id) }
    val orders = async { fetchOrders(id) }
    Dashboard(user.await(), orders.await())
}
```

- `launch` is fire-and-forget; `async` returns a `Deferred<T>`.
- Prefer `coroutineScope` over `GlobalScope` — global coroutines outlive their logical parent.

## Result and error handling
- `runCatching { }` wraps a block in `Result<T>` without try/catch noise.
- Chain with `map`, `recover`, `onSuccess`, `onFailure`.
- Exceptions for genuinely exceptional paths; `Result` for recoverable failures.

```kotlin
val result = runCatching { parse(input) }
    .map { it.validate() }
    .recover { _ -> ParsedValue.empty() }       // recover: failure → success fallback
    .onFailure { e -> log.warn("parse failed", e) }
```

## Scope functions — pick the right one

| Function | Receiver as | Returns | Use when |
|---|---|---|---|
| `let` | `it` | lambda result | null-guard, transform, introduce local name |
| `apply` | `this` | receiver | builder / configure-and-return |
| `run` | `this` | lambda result | scope + transform |
| `also` | `it` | receiver | side-effect (logging) without changing the chain |
| `with` | `this` | lambda result | operations on a non-nullable object without extension |

Do not nest scope functions more than one level — it destroys readability.

## Extension functions
- Additive utilities on existing types. Place in the package that uses them, not in a companion.
- Do not shadow members — extension functions lose to member functions at call sites.

```kotlin
fun String.toSlug() = lowercase().replace(Regex("[^a-z0-9]+"), "-").trim('-')
```

## Flow — async sequences
- `Flow<T>` is cold (lazy); it does not run until collected.
- `StateFlow` for observable mutable state; `SharedFlow` for events.
- `map`, `filter`, `flatMapLatest`, `debounce` — use operators over manual loops.

```kotlin
val prices: Flow<BigDecimal> = priceRepo.watch(symbol)
    .filter { it > BigDecimal.ZERO }
    .distinctUntilChanged()
```

## Tests
- JUnit 5 or Kotest for test structure; MockK for Kotlin-friendly mocking.
- `runTest { }` from `kotlinx-coroutines-test` for coroutine tests — no manual dispatchers.

```kotlin
@Test
fun `fetch returns cached value`() = runTest {
    val repo = FakeRepo(listOf(user))
    assertThat(repo.find(user.id)).isEqualTo(user)
}
```

## Avoid
- `!!` — if you know it is non-null, prove it with a `requireNotNull` or type the field as non-nullable.
- Translating Java idioms (`if (x != null)` → use `?.` and `?:`).
- Nesting scope functions more than one level deep.
- `lateinit var` outside dependency injection — prefer `by lazy` or constructor injection.
- `GlobalScope` — ties coroutines to the process lifetime instead of a logical scope.
