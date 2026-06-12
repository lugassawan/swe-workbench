# Caching — Rust — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```rust
// file: cache_aside.rs
use std::{
    collections::HashMap,
    hash::Hash,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

struct Entry<V> {
    value: V,
    expires_at: Instant,
}

pub struct CacheAside<K, V> {
    // A single Mutex over the whole store is simple and correct for moderate contention.
    // Trade-off: the lock is held while the loader runs, so slow loaders (e.g. HTTP calls)
    // block all concurrent reads for any key. For high-throughput use, prefer a per-key
    // lock map (e.g. DashMap) to avoid global blocking.
    store: Mutex<HashMap<K, Entry<V>>>,
    ttl: Duration,
}

impl<K: Eq + Hash + Clone, V: Clone> CacheAside<K, V> {
    pub fn new(ttl: Duration) -> Arc<Self> {
        Arc::new(Self {
            store: Mutex::new(HashMap::new()),
            ttl,
        })
    }

    /// Returns the cached value, or calls `loader` under the lock (single-flight).
    pub fn get_or_load(&self, key: K, loader: impl FnOnce(&K) -> V) -> V {
        let mut store = self.store.lock().unwrap();
        if let Some(e) = store.get(&key) {
            if Instant::now() < e.expires_at {
                return e.value.clone();
            }
        }
        // Lock is still held — only one thread recomputes for this key.
        let value = loader(&key);
        store.insert(key, Entry { value: value.clone(), expires_at: Instant::now() + self.ttl });
        value
    }
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```rust
// ✗ release lock before calling loader — other threads race to recompute the same key
let mut store = self.store.lock().unwrap();
if let Some(e) = store.get(&key) {
    if Instant::now() < e.expires_at { return e.value.clone(); }
}
drop(store); // ✗ multiple threads now call loader concurrently for the same key
let value = loader(&key);
```
