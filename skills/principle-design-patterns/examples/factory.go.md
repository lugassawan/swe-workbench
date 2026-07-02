# Factory Method — Go — Notification Channel

## Problem

A notification service must deliver messages over Email, SMS, or Push depending on a
user's configured preference. Constructing the right channel at every call site scatters
`switch` blocks throughout the codebase. The Factory Method centralizes that decision:
one function inspects the kind string and returns the correct unexported implementation,
keeping all construction logic in a single place.

## Implementation

```go
// file: channel.go
package notify

import "fmt"

// Channel is the contract every notification backend must satisfy.
type Channel interface {
	Send(msg string)
}

type emailChannel struct{}
type smsChannel struct{}
type pushChannel struct{}

func (e emailChannel) Send(msg string) { fmt.Println("[email]", msg) }
func (s smsChannel) Send(msg string)   { fmt.Println("[sms]", msg) }
func (p pushChannel) Send(msg string)  { fmt.Println("[push]", msg) }

// NewChannel is the factory: one switch here, nowhere else.
func NewChannel(kind string) (Channel, error) {
	switch kind {
	case "email":
		return emailChannel{}, nil
	case "sms":
		return smsChannel{}, nil
	case "push":
		return pushChannel{}, nil
	default:
		return nil, fmt.Errorf("unknown channel kind: %q", kind)
	}
}
```

```go
// file: main.go
package main

import (
	"fmt"
	"example/notify"
)

func main() {
	for _, kind := range []string{"email", "sms", "push"} {
		ch, err := notify.NewChannel(kind)
		if err != nil {
			fmt.Println("error:", err)
			continue
		}
		ch.Send("Your order has shipped.")
	}
}
```

## Common Mistake

Repeated `switch` blocks at every call site — adding a `PushChannel` requires hunting
down and editing every site individually.

```go
// ✗ construction scattered — every call site must repeat this switch
func notify(kind, msg string) {
	switch kind {
	case "email":
		emailChannel{}.Send(msg)   // ✗ duplicated construction
	case "sms":
		smsChannel{}.Send(msg)     // ✗ duplicated construction
	// ✗ adding push requires editing every switch in the codebase
	}
}
```
