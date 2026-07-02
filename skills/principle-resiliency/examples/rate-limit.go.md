# Resiliency — Go — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```go
// file: ratelimit.go
// Requires Go 1.22+ (integer range in for loop; built-in min added in Go 1.21).
package ratelimit

import (
	"fmt"
	"math/rand"
	"sync"
	"time"
)

type TokenBucket struct {
	mu           sync.Mutex
	capacity     float64
	refillPerSec float64
	tokens       float64
	lastRefill   time.Time
}

func NewTokenBucket(capacity, refillPerSec float64) *TokenBucket {
	return &TokenBucket{
		capacity:     capacity,
		refillPerSec: refillPerSec,
		tokens:       capacity,
		lastRefill:   time.Now(),
	}
}

func (b *TokenBucket) TryAcquire() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	elapsed := time.Since(b.lastRefill).Seconds()
	b.tokens = min(b.capacity, b.tokens+elapsed*b.refillPerSec)
	b.lastRefill = time.Now()
	if b.tokens >= 1 {
		b.tokens--
		return true
	}
	return false
}

func CallWithRateLimit(bucket *TokenBucket, op func() error, maxAttempts int) error {
	for attempt := range maxAttempts {
		if bucket.TryAcquire() {
			return op()
		}
		// Jitter prevents synchronized retries (thundering herd).
		jitter := time.Duration(float64(time.Millisecond) * (0.5 + rand.Float64()) * float64(1<<attempt))
		time.Sleep(jitter)
	}
	return fmt.Errorf("rate limit exhausted after %d attempts", maxAttempts)
}
```

```go
// file: main.go
package main

import (
	"fmt"
	"ratelimit"
)

func main() {
	bucket := ratelimit.NewTokenBucket(3, 1.0) // 3-token burst, 1/sec refill

	for i := range 5 {
		err := ratelimit.CallWithRateLimit(bucket, func() error {
			fmt.Printf("ok-%d\n", i)
			return nil
		}, 5)
		if err != nil {
			fmt.Printf("rejected: %v\n", err)
		}
	}
}
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```go
type FixedWindowUnsafe struct {
	limit       int
	windowSec   float64
	count       int
	windowStart time.Time
}

func (f *FixedWindowUnsafe) TryAcquire() bool {
	if time.Since(f.windowStart).Seconds() >= f.windowSec {
		f.count = 0            // ✗ hard reset enables boundary burst
		f.windowStart = time.Now()
	}
	if f.count < f.limit { f.count++; return true }
	return false
}
```
