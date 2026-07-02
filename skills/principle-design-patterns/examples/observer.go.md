# Observer — Go — Order Status Notifications

## Problem

An `Order` changes status — "shipped", "delivered" — and multiple independent systems must
react: email, SMS, and audit log. Go's first-class functions make the Observer pattern
idiomatic without an interface: `Order` holds a slice of `Listener` functions and calls each
when a transition occurs. Listeners are registered as closures; the emitter stays ignorant of
their contents.

## Implementation

```go
// file: order.go
package order

// Listener is a function notified on every status change.
type Listener func(status string)

// Order emits status changes to all registered Listeners.
type Order struct {
	listeners []Listener
	status    string
}

func New() *Order { return &Order{status: "pending"} }

// AddListener registers fn to receive future status updates.
func (o *Order) AddListener(fn Listener) {
	o.listeners = append(o.listeners, fn)
}

func (o *Order) notify(status string) {
	for _, fn := range o.listeners {
		fn(status)
	}
}

func (o *Order) Ship() {
	o.status = "shipped"
	o.notify(o.status)
}

func (o *Order) Deliver() {
	o.status = "delivered"
	o.notify(o.status)
}
```

```go
// file: main.go
package main

import (
	"fmt"
	"example/order"
)

func main() {
	o := order.New()

	o.AddListener(func(s string) { fmt.Printf("Email: order is now %s\n", s) })
	o.AddListener(func(s string) { fmt.Printf("SMS: order is now %s\n", s) })
	o.AddListener(func(s string) { fmt.Printf("Audit: status changed to %s\n", s) })

	o.Ship()
	// Email: order is now shipped
	// SMS: order is now shipped
	// Audit: status changed to shipped
}
```

## Common Mistake

Calling notification services directly from `Ship` or `Deliver` couples `Order` to every
downstream system; adding a new channel means editing the core domain type.

```go
// ✗ Order directly calls services — adding a new notification requires editing Order
func (o *Order) Ship() {
	o.status = "shipped"
	emailService.Send("shipped")  // ✗ hard dependency on emailService
	smsService.Send("shipped")    // ✗ hard dependency on smsService
	// ✗ must edit Order to add audit log
}
```
