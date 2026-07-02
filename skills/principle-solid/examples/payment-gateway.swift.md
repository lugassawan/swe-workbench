# DIP & OCP — Swift — Payment Processing

## Problem
`OrderService` depends on a `PaymentGateway` protocol. Swift protocols are first-class: a class,
struct, or enum can conform. Structs are used for stateless gateways (value semantics); the
protocol type is stored as `any PaymentGateway` (Swift 5.7+ existential syntax). Adding
`PayPalGateway` is a new struct; `OrderService` is never edited (OCP). The gateway is injected
at `init` time (DIP).

## Implementation

```swift
// file: PaymentGateway.swift
protocol PaymentGateway {
    func charge(amountCents: Int, reference: String) -> Bool
}
```

```swift
// file: StripeGateway.swift
struct StripeGateway: PaymentGateway {
    func charge(amountCents: Int, reference: String) -> Bool {
        print("Stripe: charging \(amountCents)¢ for \(reference)")
        return true
    }
}
```

```swift
// file: PayPalGateway.swift
// Adding PayPal requires no edits to OrderService — this is OCP.
struct PayPalGateway: PaymentGateway {
    func charge(amountCents: Int, reference: String) -> Bool {
        print("PayPal: charging \(amountCents)¢ for \(reference)")
        return true
    }
}
```

```swift
// file: OrderService.swift  (requires Swift 5.7+ for `any` existential syntax)
final class OrderService {
    private let gateway: any PaymentGateway // injected — never constructed here (DIP)

    init(gateway: any PaymentGateway) {
        self.gateway = gateway
    }

    func placeOrder(item: String, amountCents: Int) -> Bool {
        print("Placing order for \"\(item)\"")
        return gateway.charge(amountCents: amountCents, reference: item)
    }
}
```

## Common Mistake

```swift
// ✗ DIP violation — OrderService stores the concrete StripeGateway type
// ✗ OCP violation — switch must be edited for every new payment method
enum PaymentMethod { case stripe, paypal }

final class BadOrderService {
    func placeOrder(item: String, cents: Int, method: PaymentMethod) -> Bool {
        switch method {                               // ✗ switch on payment type
        case .stripe:                                // ✗ concrete logic inline
            print("Stripe: charging \(cents)¢")
            return true
        case .paypal:                                // ✗ edit required per new provider
            print("PayPal: charging \(cents)¢")
            return true
        }
    }
}
```
