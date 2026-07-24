# Strategy — Swift — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules at runtime — percent-off, buy-one-get-one,
or no discount — chosen from configuration. Swift stores function types as first-class values,
so a `(Int) -> Int` stored in `Checkout` is all that is needed. Factory closures produce each
strategy; no protocol conformance or class hierarchy is required.

## Implementation

```swift
// file: Discount.swift
typealias DiscountFn = (Int) -> Int

func percentOff(_ pct: Int) -> DiscountFn {
    { cents in Int((Double(cents) * Double(100 - pct) / 100).rounded()) }
}

let bogo: DiscountFn = { cents in cents / 2 }

let noDiscount: DiscountFn = { cents in cents }
```

```swift
// file: Checkout.swift
struct Checkout {
    var discount: DiscountFn

    func total(_ itemCents: [Int]) -> Int {
        let subtotal = itemCents.reduce(0, +)
        return discount(subtotal)
    }
}
```

```swift
// file: main.swift
let items = [1000, 2000, 500] // 35.00

var co = Checkout(discount: percentOff(10))
print(co.total(items)) // 3150

co.discount = bogo
print(co.total(items)) // 1750

co.discount = noDiscount
print(co.total(items)) // 3500
```

## Common Mistake

A `switch` on a discount-type enum inside `total` requires editing `Checkout` for every new
pricing rule, and leaks algorithm knowledge into the caller.

```swift
// ✗ branching on type inside checkout — adding a new discount requires editing total
enum DiscountType { case percent(Int), bogo, none }

func badTotal(_ itemCents: [Int], discount: DiscountType) -> Int {
    let subtotal = itemCents.reduce(0, +)
    switch discount {                              // ✗ caller must enumerate all variants
    case .percent(let pct):                       // ✗ algorithm baked into checkout
        return Int((Double(subtotal) * Double(100 - pct) / 100).rounded())
    case .bogo:                                   // ✗ edit required per new discount type
        return subtotal / 2
    case .none:
        return subtotal
    }
}
```
