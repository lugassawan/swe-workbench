# Strategy — Kotlin — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules at runtime — percent-off, buy-one-get-one,
or no discount — chosen from configuration. Kotlin's `fun interface` (SAM) lets lambdas satisfy
the strategy contract directly, and factory functions produce each variant concisely. No abstract
class hierarchy or verbose anonymous-class syntax is needed.

## Implementation

```kotlin
// file: Discount.kt
fun interface Discount {
    fun apply(cents: Int): Int
}

fun percentOff(pct: Int): Discount = Discount { cents ->
    (cents * (100 - pct) / 100.0).toInt()
}

val bogo: Discount = Discount { cents -> cents / 2 }

val noDiscount: Discount = Discount { cents -> cents }
```

```kotlin
// file: Checkout.kt
class Checkout(private val discount: Discount) {
    fun total(vararg itemCents: Int): Int {
        val subtotal = itemCents.sum()
        return discount.apply(subtotal)
    }
}
```

```kotlin
// file: main.kt
fun main() {
    val items = intArrayOf(1000, 2000, 500) // 35.00

    println(Checkout(percentOff(10)).total(*items)) // 3150
    println(Checkout(bogo).total(*items))           // 1750
    println(Checkout(noDiscount).total(*items))     // 3500
}
```

## Common Mistake

A `when` expression inside `total` that switches on a discount-type enum requires a code edit
for every new pricing rule and leaks algorithm details into checkout.

```kotlin
// ✗ branching on type inside checkout — adding a new discount requires editing total
enum class DiscountType { PERCENT, BOGO, NONE }

fun badTotal(itemCents: IntArray, type: DiscountType, pct: Int = 0): Int {
    val subtotal = itemCents.sum()
    return when (type) {                       // ✗ caller must enumerate all variants
        DiscountType.PERCENT ->                // ✗ algorithm baked into checkout
            (subtotal * (100 - pct) / 100.0).toInt()
        DiscountType.BOGO ->                   // ✗ edit required per new discount type
            subtotal / 2
        DiscountType.NONE -> subtotal
    }
}
```
