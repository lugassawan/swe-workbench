# Observer — Swift — Order Status Notifications

## Problem

An `Order` transitions through statuses — "shipped", "delivered" — and email, SMS, and audit
systems must react independently. Swift closures are first-class, so listeners are stored as
`[(String) -> Void]` — no protocol required for simple cases. `NotificationCenter` is the
language-native alternative for cross-module fanout, but the closure approach shown here is
clearer for explicit, in-process subscribers.

## Implementation

```swift
// file: Order.swift
final class Order {
    private var listeners: [(String) -> Void] = []
    private(set) var status = "pending"

    func addListener(_ fn: @escaping (String) -> Void) {
        listeners.append(fn)
    }

    private func notifyListeners() {
        listeners.forEach { $0(status) }
    }

    func ship() {
        status = "shipped"
        notifyListeners()
    }

    func deliver() {
        status = "delivered"
        notifyListeners()
    }
}
```

```swift
// file: main.swift
let order = Order()

order.addListener { s in print("Email: order is now \(s)") }
order.addListener { s in print("SMS: order is now \(s)") }
order.addListener { s in print("Audit: status changed to \(s)") }

order.ship()
// Email: order is now shipped
// SMS: order is now shipped
// Audit: status changed to shipped

order.deliver()
// Email: order is now delivered
// SMS: order is now delivered
// Audit: status changed to delivered
```

## Common Mistake

Calling `emailService` and `smsService` directly from `ship()` couples `Order` to every
notification channel; adding audit logging requires editing the domain class.

```swift
// ✗ Order directly calls services — adding a new notification requires editing Order
func ship() {
    status = "shipped"
    emailService.send("shipped")   // ✗ hard dependency on EmailService
    smsService.send("shipped")     // ✗ hard dependency on SmsService
    // ✗ must edit Order to add audit log
}
```
