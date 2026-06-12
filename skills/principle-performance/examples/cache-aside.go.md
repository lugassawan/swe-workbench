# Caching — Go — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```go
// file: cache-aside.go
package cache

import (
	"sync"
	"time"
)

type entry[V any] struct {
	value     V
	expiresAt time.Time
}

// Cache is a generic cache-aside store with single-flight on cold/expired keys.
type Cache[V any] struct {
	mu     sync.Mutex
	store  map[string]entry[V]
	// inflight gates concurrent misses: only one goroutine recomputes per key.
	inflight map[string]*call[V]
	ttl    time.Duration
	loader func(key string) (V, error)
}

type call[V any] struct {
	wg  sync.WaitGroup
	val V
	err error
}

func New[V any](ttl time.Duration, loader func(string) (V, error)) *Cache[V] {
	return &Cache[V]{
		store:    make(map[string]entry[V]),
		inflight: make(map[string]*call[V]),
		ttl:      ttl,
		loader:   loader,
	}
}

func (c *Cache[V]) Get(key string) (V, error) {
	c.mu.Lock()
	if e, ok := c.store[key]; ok && time.Now().Before(e.expiresAt) {
		c.mu.Unlock()
		return e.value, nil
	}
	// Single-flight: reuse an in-progress recomputation for the same key.
	if cl, ok := c.inflight[key]; ok {
		c.mu.Unlock()
		cl.wg.Wait()
		return cl.val, cl.err
	}
	cl := &call[V]{}
	cl.wg.Add(1)
	c.inflight[key] = cl
	c.mu.Unlock()

	cl.val, cl.err = c.loader(key)
	cl.wg.Done()

	c.mu.Lock()
	if cl.err == nil {
		c.store[key] = entry[V]{value: cl.val, expiresAt: time.Now().Add(c.ttl)}
	}
	// Always remove the inflight entry — on error we don't cache, so the next caller retries.
	delete(c.inflight, key)
	c.mu.Unlock()

	return cl.val, cl.err
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```go
// ✗ no single-flight — concurrent misses all call loader simultaneously
c.mu.Lock()
if e, ok := c.store[key]; ok && time.Now().Before(e.expiresAt) {
    c.mu.Unlock()
    return e.value, nil
}
c.mu.Unlock()
val, err := c.loader(key) // ✗ N goroutines all reach here on a cold key
```
