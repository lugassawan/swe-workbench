# Resiliency — Rust — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```rust
// file: token_bucket.rs
use std::time::Instant;

pub struct TokenBucket {
    capacity: f64,
    refill_per_ms: f64,
    tokens: f64,
    last_refill: Instant,
}

impl TokenBucket {
    pub fn new(capacity: f64, refill_per_second: f64) -> Self {
        Self {
            capacity,
            refill_per_ms: refill_per_second / 1000.0,
            tokens: capacity,
            last_refill: Instant::now(),
        }
    }

    pub fn try_acquire(&mut self) -> bool {
        let elapsed_ms = self.last_refill.elapsed().as_millis() as f64;
        self.tokens = f64::min(self.capacity, self.tokens + elapsed_ms * self.refill_per_ms);
        self.last_refill = Instant::now();
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            true
        } else {
            false
        }
    }
}
```

```rust
// file: main.rs
mod token_bucket;
use token_bucket::TokenBucket;
use std::time::Duration;

fn call_with_rate_limit<F, T>(bucket: &mut TokenBucket, op: F, max_attempts: u32) -> Option<T>
where
    F: Fn() -> T,
{
    for attempt in 0..max_attempts {
        if bucket.try_acquire() {
            return Some(op());
        }
        // Jitter prevents synchronized retries (thundering herd).
        let base_ms = (1u64 << attempt).min(1000);
        let jitter_ms = base_ms / 2 + (rand_jitter() % (base_ms / 2 + 1));
        std::thread::sleep(Duration::from_millis(jitter_ms));
    }
    None
}

fn rand_jitter() -> u64 { 42 } // placeholder — use rand::Rng in production

fn main() {
    let mut bucket = TokenBucket::new(3.0, 1.0);
    for i in 0..5u32 {
        match call_with_rate_limit(&mut bucket, || format!("ok-{i}"), 5) {
            Some(r) => println!("{r}"),
            None    => println!("rejected"),
        }
    }
}
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```rust
struct FixedWindowUnsafe {
    limit: u32,
    window_ms: u128,
    count: u32,
    window_start: std::time::Instant,
}

impl FixedWindowUnsafe {
    fn try_acquire(&mut self) -> bool {
        if self.window_start.elapsed().as_millis() >= self.window_ms {
            self.count = 0;           // ✗ hard reset enables boundary burst
            self.window_start = std::time::Instant::now();
        }
        if self.count < self.limit { self.count += 1; true } else { false }
    }
}
```
