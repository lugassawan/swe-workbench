# Resiliency — Rust — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```rust
// file: idempotency.rs
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

#[derive(Clone)]
enum Entry<T: Clone> {
    Pending,
    Completed(T),
}

pub struct IdempotencyStore<T: Clone> {
    store: Arc<Mutex<HashMap<String, Entry<T>>>>,
}

impl<T: Clone> IdempotencyStore<T> {
    pub fn new() -> Self {
        Self { store: Arc::new(Mutex::new(HashMap::new())) }
    }

    pub fn execute<F>(&self, key: &str, operation: F) -> Result<T, String>
    where
        F: FnOnce() -> T,
    {
        {
            let mut guard = self.store.lock().unwrap();
            match guard.get(key) {
                Some(Entry::Completed(r)) => return Ok(r.clone()),
                Some(Entry::Pending) => return Err(format!("key '{key}' already in-flight")),
                None => {
                    // Reserve BEFORE executing — concurrent retry sees Pending and stops.
                    guard.insert(key.to_string(), Entry::Pending);
                }
            }
        }

        let result = operation();
        self.store.lock().unwrap().insert(key.to_string(), Entry::Completed(result.clone()));
        Ok(result)
    }
}
```

```rust
// file: main.rs
mod idempotency;
use idempotency::IdempotencyStore;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

fn main() {
    let store = IdempotencyStore::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let calls2 = calls.clone();

    let key = "order-abc-attempt-1";
    let r1 = store.execute(key, || { calls.fetch_add(1, Ordering::SeqCst); "ch_123" }).unwrap();
    let r2 = store.execute(key, || { calls2.fetch_add(1, Ordering::SeqCst); "ch_123" }).unwrap();

    assert_eq!(r1, r2);
    assert_eq!(calls.load(Ordering::SeqCst), 1, "charge executed more than once");
    println!("charge_id={r1} calls=1");
}
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```rust
fn execute_unsafe<T: Clone, F: FnOnce() -> T>(store: &mut HashMap<String, T>, key: &str, op: F) -> T {
    let result = op();                          // ✗ side effect runs first
    store.insert(key.to_string(), result.clone()); // ✗ key recorded after — concurrent retry double-charges
    result
}
```
