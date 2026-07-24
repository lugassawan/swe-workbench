# Observer — Kotlin — Order Status Notifications

## Problem

An `Order` emits status changes — "shipped", "delivered" — and email, SMS, and audit systems
must all react. Kotlin's `fun interface` (SAM interface) lets lambdas serve as observers with
no boilerplate, while keeping the emitter fully decoupled from every concrete listener. Adding
a new channel is one `addObserver` call at the composition root; `Order` is never touched.

## Implementation

```kotlin
// file: Order.kt
fun interface OrderObserver {
    fun onStatusChanged(status: String)
}

class Order {
    private val observers = mutableListOf<OrderObserver>()
    private var status = "pending"

    fun addObserver(observer: OrderObserver) {
        observers += observer
    }

    private fun notifyObservers() = observers.forEach { it.onStatusChanged(status) }

    fun ship() {
        status = "shipped"
        notifyObservers()
    }

    fun deliver() {
        status = "delivered"
        notifyObservers()
    }
}
```

```kotlin
// file: main.kt
fun main() {
    val order = Order()

    order.addObserver { s -> println("Email: order is now $s") }
    order.addObserver { s -> println("SMS: order is now $s") }
    order.addObserver { s -> println("Audit: status changed to $s") }

    order.ship()
    // Email: order is now shipped
    // SMS: order is now shipped
    // Audit: status changed to shipped

    order.deliver()
    // Email: order is now delivered
    // SMS: order is now delivered
    // Audit: status changed to delivered
}
```

## Common Mistake

Calling notification services from within `ship()` or `deliver()` makes `Order` own the
wiring — each new channel requires an edit to the domain class.

```kotlin
// ✗ Order directly calls services — adding a new notification requires editing Order
fun ship() {
    status = "shipped"
    emailService.send("shipped")   // ✗ hard dependency on EmailService
    smsService.send("shipped")     // ✗ hard dependency on SmsService
    // ✗ must edit Order to add audit log
}
```
