# Bounded Fan-out — Rust — buffer_unordered stream combinator

## Problem

Fetch N items concurrently using async Rust, capping inflight futures at K=5 with
`buffer_unordered`. Each future carries its original index so results can be sorted back
into submission order after collection. The stream combinator handles the concurrency
window automatically — no manual semaphore bookkeeping required.

## Implementation

```rust
// file: bounded-fan-out.rs
use futures::stream::{self, StreamExt};
use std::time::Duration;
use tokio::time::sleep;

async fn fetch(id: &str) -> String {
    sleep(Duration::from_millis(10)).await;
    format!("result-{}", id)
}

#[tokio::main]
async fn main() {
    let ids = vec!["a", "b", "c", "d", "e", "f", "g", "h"];
    const K: usize = 5;

    // Enumerate to carry the original index through the async boundary.
    let mut pairs: Vec<(usize, String)> = stream::iter(ids.iter().copied().enumerate())
        .map(|(i, id)| async move { (i, fetch(id).await) })
        .buffer_unordered(K) // at most K futures polled at once
        .collect()
        .await;

    pairs.sort_by_key(|(i, _)| *i); // restore original order
    let results: Vec<String> = pairs.into_iter().map(|(_, v)| v).collect();
    println!("{:?}", results);
}
```

## Common Mistake

`join_all` launches every future at once with no concurrency cap.

```rust
use futures::future::join_all;

// ✗ all N futures are polled simultaneously — no cap
async fn bad_fan_out(ids: &[&str]) -> Vec<String> {
    join_all(ids.iter().copied().map(|id| fetch(id))).await // ✗ unbounded inflight
}
```
