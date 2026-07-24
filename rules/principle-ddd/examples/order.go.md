# Light DDD — Go — Order Aggregate

## Problem

Go has no `immutable` or `final` keyword — value object semantics come from
unexported fields, value receivers, and the absence of setters. Callers cannot
mutate `Money` directly; they go through constructors or methods that return new
values. The `Order` aggregate root hides `lines []orderLine` behind an unexported
field so only `AddLine` and `Submit` can mutate it, keeping the draft-only
invariant enforceable. `AddLine` returns `error` (Go's idiomatic flow — no
exceptions) and `OrderRepository` is a plain `interface` — a domain port with
zero infrastructure coupling.

## Implementation

```go
// file: money.go
package ddd

import "fmt"

type Money struct {
	minorUnits int64
	currency   string
}

func NewMoney(minorUnits int64, currency string) Money {
	return Money{minorUnits: minorUnits, currency: currency}
}

func (m Money) Plus(other Money) (Money, error) {
	if m.currency != other.currency {
		return Money{}, fmt.Errorf("currency mismatch: %s vs %s", m.currency, other.currency)
	}
	return Money{minorUnits: m.minorUnits + other.minorUnits, currency: m.currency}, nil
}

func (m Money) Equal(other Money) bool {
	return m.minorUnits == other.minorUnits && m.currency == other.currency
}
```

```go
// file: order.go
package ddd

import "errors"

type status int

const (
	draft status = iota
	submitted
)

type orderLine struct {
	sku   string
	price Money
}

type Order struct {
	ID     string
	status status
	lines  []orderLine // unexported: only mutated through aggregate root methods
}

func NewOrder(id string) *Order {
	return &Order{ID: id}
}

func (o *Order) AddLine(sku string, price Money) error {
	if o.status == submitted {
		return errors.New("cannot add lines to a submitted order")
	}
	o.lines = append(o.lines, orderLine{sku: sku, price: price})
	return nil
}

func (o *Order) Submit()       { o.status = submitted }
func (o *Order) LineCount() int { return len(o.lines) }
```

```go
// file: repository.go
package ddd

type OrderRepository interface {
	Find(id string) (*Order, bool)
	Save(order *Order)
}
```

```go
// file: main.go
package main

import (
	"ddd"
	"fmt"
)

func main() {
	order := ddd.NewOrder("ord-1")
	_ = order.AddLine("SKU-1", ddd.NewMoney(1299, "USD"))
	order.Submit()
	if err := order.AddLine("SKU-2", ddd.NewMoney(500, "USD")); err != nil {
		fmt.Println("rejected:", err) // rejected: cannot add lines to a submitted order
	}
}
```

## Common Mistake

Exporting `Lines` as a public field lets callers `append` after `Submit()`, bypassing the aggregate root.
```go
type Order struct {
	ID     string
	Lines []OrderLine // ✗ callers can append after Submit() — invariant broken (OrderLine also exported)
}
```
