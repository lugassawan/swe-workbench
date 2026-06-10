# DIP & OCP — Kotlin — Payment Processing

## Problem
`OrderService` depends on a `PaymentGateway` interface, never a concrete class. Kotlin's
`interface` keyword mirrors Java's but gains default implementations and is null-safe by default.
`object` declarations (singletons) are idiomatic for stateless gateways. Adding `PayPalGateway`
is a new file; `OrderService` is never edited (OCP). The gateway is constructor-injected (DIP).

## Implementation

```kotlin
// file: PaymentGateway.kt
interface PaymentGateway {
    fun charge(amountCents: Int, reference: String): Boolean
}
```

```kotlin
// file: StripeGateway.kt
object StripeGateway : PaymentGateway {
    override fun charge(amountCents: Int, reference: String): Boolean {
        println("Stripe: charging ${amountCents}¢ for $reference")
        return true
    }
}
```

```kotlin
// file: PayPalGateway.kt
// Adding PayPal requires no edits to OrderService — this is OCP.
object PayPalGateway : PaymentGateway {
    override fun charge(amountCents: Int, reference: String): Boolean {
        println("PayPal: charging ${amountCents}¢ for $reference")
        return true
    }
}
```

```kotlin
// file: OrderService.kt
class OrderService(private val gateway: PaymentGateway) { // injected (DIP)
    fun placeOrder(item: String, amountCents: Int): Boolean {
        println("Placing order for \"$item\"")
        return gateway.charge(amountCents, item)
    }
}
```

## Common Mistake

```kotlin
// ✗ DIP violation — concrete class constructed inside OrderService
// ✗ OCP violation — when keyword forces edits for every new provider
class BadOrderService {
    fun placeOrder(item: String, cents: Int, method: String): Boolean {
        return when (method) {                        // ✗ switch on payment type
            "stripe" -> StripeGateway.charge(cents, item)  // ✗ direct dep on concrete
            "paypal" -> PayPalGateway.charge(cents, item)  // ✗ direct dep on concrete, edit required per provider
            else -> error("Unknown payment method: $method")
        }
    }
}
```
