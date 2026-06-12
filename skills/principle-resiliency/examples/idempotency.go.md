# Resiliency — Go — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```go
// file: idempotency.go
package idempotency

import (
	"errors"
	"sync"
)

type status int

const (
	pending   status = iota
	completed status = iota
)

type entry[T any] struct {
	status status
	result T
}

type Store[T any] struct {
	mu    sync.Mutex
	items map[string]*entry[T]
}

func NewStore[T any]() *Store[T] {
	return &Store[T]{items: make(map[string]*entry[T])}
}

var ErrInFlight = errors.New("key already in-flight")

func (s *Store[T]) Execute(key string, op func() (T, error)) (T, error) {
	s.mu.Lock()
	e, ok := s.items[key]
	if ok && e.status == completed {
		s.mu.Unlock()
		return e.result, nil
	}
	if ok && e.status == pending {
		s.mu.Unlock()
		var zero T
		return zero, ErrInFlight
	}
	// Reserve BEFORE executing — concurrent retry sees pending and stops.
	s.items[key] = &entry[T]{status: pending}
	s.mu.Unlock()

	result, err := op()
	if err != nil {
		s.mu.Lock()
		delete(s.items, key)
		s.mu.Unlock()
		return result, err
	}

	s.mu.Lock()
	s.items[key] = &entry[T]{status: completed, result: result}
	s.mu.Unlock()
	return result, nil
}
```

```go
// file: main.go
package main

import (
	"fmt"
	"idempotency"
)

func main() {
	store := idempotency.NewStore[map[string]any]()
	calls := 0
	charge := func() (map[string]any, error) {
		calls++
		return map[string]any{"charge_id": "ch_123", "amount": 100}, nil
	}

	key := "order-abc-attempt-1"
	r1, _ := store.Execute(key, charge)
	r2, _ := store.Execute(key, charge) // duplicate — returns cached result

	fmt.Println(r1["charge_id"] == r2["charge_id"]) // true
	fmt.Printf("calls=%d\n", calls)                 // calls=1
}
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```go
func executeUnsafe(key string, op func() (any, error)) (any, error) {
    result, err := op()        // ✗ side effect runs first
    store[key] = result        // ✗ key recorded after — concurrent retry double-charges
    return result, err
}
```
