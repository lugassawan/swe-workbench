# DIP & OCP — Go — Payment Processing

## Problem
`OrderService` charges payments through an interface it defines itself — the consumer-defines-
the-interface pattern. Go's implicit satisfaction means no import cycle: `StripeGateway` and
`PayPalGateway` implement `PaymentGateway` without importing the `order` package. Adding a new
provider is a new file; `OrderService` is never edited (OCP). The interface is injected (DIP).

## Implementation

```go
// file: order_service.go
package order

import "fmt"

// PaymentGateway is defined by the consumer (order package), not the provider.
type PaymentGateway interface {
	Charge(amountCents int, reference string) bool
}

type OrderService struct {
	gateway PaymentGateway // injected — never constructed here (DIP)
}

func NewOrderService(g PaymentGateway) *OrderService {
	return &OrderService{gateway: g}
}

func (s *OrderService) PlaceOrder(item string, amountCents int) bool {
	fmt.Printf("Placing order for %q\n", item)
	return s.gateway.Charge(amountCents, item)
}
```

```go
// file: stripe_gateway.go
package stripe

import "fmt"

type Gateway struct{}

func (g *Gateway) Charge(amountCents int, reference string) bool {
	fmt.Printf("Stripe: charging %d¢ for %s\n", amountCents, reference)
	return true
}
```

```go
// file: paypal_gateway.go
// Adding PayPal requires no edits to OrderService — this is OCP.
package paypal

import "fmt"

type Gateway struct{}

func (g *Gateway) Charge(amountCents int, reference string) bool {
	fmt.Printf("PayPal: charging %d¢ for %s\n", amountCents, reference)
	return true
}
```

```go
// file: main.go
// Go's implicit satisfaction: stripe.Gateway satisfies order.PaymentGateway without
// importing the order package — the consumer-defines-interface pattern in action.
package main

import (
	"example/order"
	"example/stripe"
)

func main() {
	svc := order.NewOrderService(&stripe.Gateway{})
	svc.PlaceOrder("widget", 1999)
}
```

## Common Mistake

```go
// ✗ DIP violation — OrderService imports the concrete stripe package
// ✗ OCP violation — adding PayPal requires editing PlaceOrder
import stripe "github.com/stripe/stripe-go/v2"

type BadOrderService struct{}

func (s *BadOrderService) PlaceOrder(item, method string, cents int) {
	if method == "stripe" {                   // ✗ switch on payment type
		stripe.Key = "sk_live_..."            // ✗ concrete SDK dep inside high-level policy
		// charge.New(params) — SDK call here
	} else if method == "paypal" {            // ✗ edit required for every new provider
		// paypal SDK call here
	}
}
```
