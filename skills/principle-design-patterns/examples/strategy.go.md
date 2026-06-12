# Strategy — Go — Checkout Discount Pricing

## Problem

A checkout must apply a pricing rule chosen at runtime from configuration — percent-off,
buy-one-get-one, or no discount. Go's first-class functions make this idiom natural: a
`Discount` function type is the strategy; factory functions return concrete strategies.
No interface or struct embedding is needed, keeping the approach idiomatic and testable.

## Implementation

```go
// file: discount.go
package checkout

// Discount is the strategy: a function from subtotal cents to discounted cents.
type Discount func(cents int) int

// PercentOff returns a Discount that takes pct% off the subtotal.
func PercentOff(pct int) Discount {
	return func(cents int) int {
		return cents * (100 - pct) / 100
	}
}

// Bogo returns a Discount that halves the subtotal (buy-one-get-one-free).
func Bogo() Discount {
	return func(cents int) int { return cents / 2 }
}

// NoDiscount returns a Discount that applies no reduction.
func NoDiscount() Discount {
	return func(cents int) int { return cents }
}
```

```go
// file: checkout.go
package checkout

// Checkout sums items and applies the chosen Discount strategy.
type Checkout struct {
	Discount Discount
}

func (c *Checkout) Total(itemCents ...int) int {
	subtotal := 0
	for _, v := range itemCents {
		subtotal += v
	}
	return c.Discount(subtotal)
}
```

```go
// file: main.go
package main

import (
	"fmt"
	"example/checkout"
)

func main() {
	items := []int{1000, 2000, 500} // 35.00

	co := &checkout.Checkout{Discount: checkout.PercentOff(10)}
	fmt.Println(co.Total(items...)) // 3150

	co.Discount = checkout.Bogo()
	fmt.Println(co.Total(items...)) // 1750

	co.Discount = checkout.NoDiscount()
	fmt.Println(co.Total(items...)) // 3500
}
```

## Common Mistake

Branching on a discount-type string inside `Total` forces edits to checkout every time a
new pricing rule is introduced.

```go
// ✗ branching on type inside checkout — adding a new discount requires editing Total
func (c *Checkout) BadTotal(discountType string, pct int, itemCents ...int) int {
	subtotal := 0
	for _, v := range itemCents {
		subtotal += v
	}
	switch discountType {
	case "percent":                        // ✗ caller must enumerate all variants
		return subtotal * (100 - pct) / 100
	case "bogo":                           // ✗ edit required per new discount type
		return subtotal / 2
	}
	return subtotal
}
```
