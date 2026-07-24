# Caching — TypeScript — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```typescript
// file: cache-aside.ts

interface Entry<V> {
  value: V;
  expiresAt: number; // Date.now() ms
}

class CacheAside<V> {
  private store = new Map<string, Entry<V>>();
  // inflight holds the in-progress Promise per key — single-flight guard.
  private inflight = new Map<string, Promise<V>>();
  private readonly ttlMs: number;
  private readonly loader: (key: string) => Promise<V>;

  constructor(ttlMs: number, loader: (key: string) => Promise<V>) {
    this.ttlMs = ttlMs;
    this.loader = loader;
  }

  async get(key: string): Promise<V> {
    const entry = this.store.get(key);
    if (entry && Date.now() < entry.expiresAt) return entry.value;

    // Single-flight: if a load is already in progress for this key, share its Promise.
    const existing = this.inflight.get(key);
    if (existing) return existing;

    const promise = this.loader(key)
      .then((value) => {
        this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
        return value;
      })
      // .finally() runs on both success and failure without swallowing the rejection —
      // cleaner than the dual-path .then(delete)/.catch(delete) pattern.
      .finally(() => this.inflight.delete(key));
    this.inflight.set(key, promise);
    return promise;
  }
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```typescript
// ✗ no inflight map — concurrent awaits all miss and call loader simultaneously
const entry = this.store.get(key);
if (entry && Date.now() < entry.expiresAt) return entry.value;
// ✗ every concurrent caller fires a separate loader() call for the same key
const value = await this.loader(key);
this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
return value;
```
