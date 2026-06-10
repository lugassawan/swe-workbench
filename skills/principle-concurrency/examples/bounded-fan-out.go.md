# Bounded Fan-out — Go — errgroup with concurrency limit

## Problem

Fetch N items concurrently but cap inflight work at K=5 using `errgroup.SetLimit`.
Pre-allocate `results[i]` and shadow the loop variables so each goroutine captures its own
`i` and writes exactly one slot — the pre-allocation, the shadow (`i, id := i, id`), and
the indexed write are three load-bearing parts of the same ordering invariant. `errgroup.WithContext`
propagates cancellation: a failed fetch signals the remaining goroutines to stop early.

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
		i, id := i, id // required for Go <1.22: range vars are shared across iterations
		g.Go(func() error {
			val, err := fetch(ctx, id)
			if err != nil {
				return err
			}
			results[i] = val // safe: pre-allocated slice + one goroutine per index slot
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
