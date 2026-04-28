name: languages-kotlin
description: Kotlin best practices including coroutines, null safety, functional patterns, and idiomatic Kotlin usage.
triggers:
  - .kt
  - build.gradle.kts
  - coroutines
  - suspend
  - Result
  - sealed interfaces

## Kotlin Best Practices
Idiomatic Kotlin
Prefer data classes

Use sealed interfaces/classes for state modeling

Use when instead of switch

Null Safety
Avoid !!

Prefer safe calls ?.

Use ?: (Elvis operator)

Coroutines
Use suspend functions

Prefer structured concurrency

Avoid GlobalScope

Collections & Functional Style
Use map, filter, fold

Prefer immutable collections

Error Handling
Use Result for controlled failures

Use exceptions sparingly

Extensions
Use extension functions to improve readability

Avoid overuse that hides logic

Interoperability
Be careful with Java interop nullability

Use @JvmStatic, @JvmOverloads when needed

DSL & Builders
Use Kotlin DSLs where appropriate

Keep them readable, not clever

## Testing
Use JUnit or KotlinTest

Keep tests expressive and concise
