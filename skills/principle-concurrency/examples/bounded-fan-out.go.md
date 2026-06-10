# Bounded Fan-out — Go — errgroup with concurrency limit

## Problem

Fetch N items concurrently but cap inflight work at K=5 using `errgroup.SetLimit`.
Pre-allocate `results[i]` so each goroutine writes its own index slot — no mutex needed.
`errgroup.WithContext` wires cancellation: if any fetch fails the remaining goroutines see
a cancelled context. Order is preserved by index, not by completion time.

## Implementation

```go
// file: bounded-fan-out.go
package main

import (
	"context"
	"fmt"
	"time"

	"golang.org/x/sync/errgroup"
)

func fetch(ctx context.Context, id string) (string, error) {
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-time.After(10 * time.Millisecond):
		return "result-" + id, nil
	}
}

func main() {
	ids := []string{"a", "b", "c", "d", "e", "f", "g", "h"}
	const K = 5
	results := make([]string, len(ids))

	g, ctx := errgroup.WithContext(context.Background())
	g.SetLimit(K) // at most K goroutines running at once

	for i, id := range ids {
		i, id := i, id
		g.Go(func() error {
			val, err := fetch(ctx, id)
			if err != nil {
				return err
			}
			results[i] = val // safe: each goroutine owns its index
			return nil
		})
	}

	if err := g.Wait(); err != nil {
		panic(err)
	}
	fmt.Println(results)
}
```

## Common Mistake

Fire-and-forget goroutines with no WaitGroup and no concurrency cap.

```go
// ✗ no WaitGroup — main exits before goroutines finish
// ✗ no limit — all N goroutines start simultaneously
func badFanOut(ids []string) {
	for _, id := range ids {
		go func(id string) { // ✗ unbounded goroutine launch
			fmt.Println(fetch(context.Background(), id))
		}(id)
	}
	// ✗ returns immediately; results are lost
}
```
