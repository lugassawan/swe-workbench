# Light DDD — Kotlin — Order Aggregate

## Problem

Kotlin `data class` gives value-object semantics with structural equality built-in, so
`Money` is compared by value without a custom `equals`. The `Order` aggregate root keeps
`_lines` private and backs a read-only `List<OrderLine>` property; the only mutation
paths are `addLine` and `submit`, which use Kotlin's `check(...)` to enforce the invariant
that lines cannot be added once an order is submitted.

## Implementation

```kotlin
// file: Money.kt
data class Money(val minorUnits: Long, val currency: String) {
    operator fun plus(other: Money): Money {
        require(currency == other.currency) {
            "currency mismatch: $currency vs ${other.currency}"
        }
        return Money(minorUnits + other.minorUnits, currency)
    }
}
```

```kotlin
// file: Order.kt
data class OrderLine(val sku: String, val price: Money)

class Order(val id: String) {

    private enum class Status { DRAFT, SUBMITTED }

    private var status = Status.DRAFT
    private val _lines: MutableList<OrderLine> = mutableListOf()

    val lines: List<OrderLine> get() = _lines.toList()
    val lineCount: Int get() = _lines.size

    fun addLine(sku: String, price: Money) {
        check(status == Status.DRAFT) { "cannot add lines to a submitted order" }
        _lines.add(OrderLine(sku, price))
    }

    fun submit() {
        status = Status.SUBMITTED
    }
}
```

```kotlin
// file: OrderRepository.kt
interface OrderRepository {
    fun find(id: String): Order?
    fun save(order: Order)
}
```

```kotlin
// file: main.kt (usage)
fun main() {
    val order = Order("ord-1")
    order.addLine("SKU-1", Money(1299, "USD"))
    order.submit()
    try {
        order.addLine("SKU-2", Money(500, "USD"))
    } catch (e: IllegalStateException) {
        println("rejected: ${e.message}")
        // rejected: cannot add lines to a submitted order
    }
}
```

## Common Mistake

Exposing `_lines` as a `val lines: MutableList<OrderLine>` property lets callers call
`.add()` directly, bypassing the aggregate root and silently breaking the submitted-order
invariant.

```kotlin
// file: Order.kt (anti-pattern)
val lines: MutableList<OrderLine> = mutableListOf() // ✗ callers can call lines.add(...) after submit() — invariant broken
```
