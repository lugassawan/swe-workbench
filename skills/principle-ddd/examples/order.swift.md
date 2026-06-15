# Light DDD — Swift — Order Aggregate

## Problem

Swift `struct` gives value-object semantics with `Equatable` structural equality, so `Money`
compares by value without custom logic. `Order` is a `class` aggregate root — reference
semantics mean a single instance is mutated in place, so invariants enforced by `addLine`
and `submit` hold for every caller that holds the same reference.

## Implementation

```swift
// file: Money.swift
enum MoneyError: Error {
    case currencyMismatch(String, String)
}

struct Money: Equatable {
    let minorUnits: Int
    let currency: String

    func plus(_ other: Money) throws -> Money {
        guard currency == other.currency else {
            throw MoneyError.currencyMismatch(currency, other.currency)
        }
        return Money(minorUnits: minorUnits + other.minorUnits, currency: currency)
    }
}
```

```swift
// file: Order.swift
enum OrderError: Error {
    case submittedOrderCannotBeModified
}

struct OrderLine {
    let sku: String
    let price: Money
}

class Order {
    private enum Status { case draft, submitted }

    let id: String
    private var status: Status = .draft
    private var lines: [OrderLine] = []

    init(id: String) { self.id = id }

    func addLine(sku: String, price: Money) throws {
        guard status == .draft else {
            throw OrderError.submittedOrderCannotBeModified
        }
        lines.append(OrderLine(sku: sku, price: price))
    }

    func submit() { status = .submitted }
    var lineCount: Int { lines.count }
}
```

```swift
// file: OrderRepository.swift
protocol OrderRepository {
    func find(id: String) -> Order?
    func save(_ order: Order)
}
```

```swift
// file: main.swift (usage)
let order = Order(id: "ord-1")
do {
    try order.addLine(sku: "SKU-1", price: Money(minorUnits: 1299, currency: "USD"))
    order.submit()
    try order.addLine(sku: "SKU-2", price: Money(minorUnits: 500, currency: "USD"))
} catch {
    print("rejected: \(error)")  // rejected: submittedOrderCannotBeModified
}
```

## Common Mistake

Removing `private` from `lines` lets any caller call `.append()` after `submit()`,
bypassing the aggregate root and silently breaking the invariant.

```swift
class Order {
    var lines: [OrderLine] = []          // ✗ callers can append after submit() — invariant broken
    private var status: Status = .draft
    func addLine(sku: String, price: Money) throws { ... }
}
```
