# Error Handling — Rust — HTTP Fetch with Retry

## Problem

Rust's `Result<T, E>` makes every failure path explicit in the type signature.
A `FetchError` enum with transient and permanent variants lets the retry loop
pattern-match on the exact cause, and deterministic pseudo-jitter keeps the
example dependency-free while still illustrating the backoff formula.

## Implementation

```rust
// file: transport.rs
#[derive(Debug)]
pub struct Response { pub status: u16, pub body: String }

#[derive(Debug)]
pub enum FetchError {
    Transient(u16),   // 5xx status
    Timeout,
    Permanent(u16),   // 4xx status
    Exhausted,
}

pub trait Transport {
    fn fetch(&self, url: &str) -> Result<Response, FetchError>;
}

pub struct FakeTransport { pub attempt: std::cell::Cell<usize> }

impl Transport for FakeTransport {
    fn fetch(&self, url: &str) -> Result<Response, FetchError> {
        if url == "/not-found" {
            return Err(FetchError::Permanent(404));
        }
        let a = self.attempt.get();
        self.attempt.set(a + 1);
        match a {
            0 | 1 => Err(FetchError::Timeout),
            _     => Ok(Response { status: 200, body: "OK".into() }),
        }
    }
}
```

```rust
// file: fetch.rs
use crate::transport::{FetchError, Response, Transport};

fn is_transient(err: &FetchError) -> bool {
    matches!(err, FetchError::Transient(_) | FetchError::Timeout)
}

/// Retries transient failures with exponential backoff + deterministic jitter.
/// timeoutMs is a parameter modelled in FakeTransport; real impl uses tokio::time::timeout.
pub fn fetch_with_retry(
    t: &dyn Transport,
    url: &str,
    max_retries: usize,
    _timeout_ms: u64,
) -> Result<Response, FetchError> {
    const BASE_MS: f64 = 100.0;
    for attempt in 0..max_retries {
        match t.fetch(url) {
            Ok(resp) => return Ok(resp),
            Err(err) if !is_transient(&err) => return Err(err), // permanent — bubble
            Err(_) => {
                // deterministic stand-in for illustration only — NOT for production.
                // Real impl: rand::thread_rng().gen_range(0.5_f64..=1.5)
                let jitter = ((attempt * 17 + 3) % 10) as f64 / 10.0 + 0.5; // [0.5, 1.4]
                let delay = BASE_MS * (1u64 << attempt) as f64 * jitter;
                let _ = delay; // sleep(delay as u64) — real impl: std::thread::sleep(Duration::from_millis(...))
            }
        }
    }
    Err(FetchError::Exhausted)
}
```

```rust
// file: main.rs
mod transport;
mod fetch;

use transport::{FakeTransport, FetchError};
use std::cell::Cell;

fn main() {
    // transient → success
    let t = FakeTransport { attempt: Cell::new(0) };
    match fetch::fetch_with_retry(&t, "/api/data", 5, 1000) {
        Ok(r)  => println!("status={} body={}", r.status, r.body),
        Err(e) => println!("error: {:?}", e),
    }

    // permanent → fail immediately
    let t2 = FakeTransport { attempt: Cell::new(0) };
    match fetch::fetch_with_retry(&t2, "/not-found", 5, 1000) {
        Ok(r)                         => println!("unexpected ok: {}", r.status),
        Err(FetchError::Permanent(c)) => println!("permanent {c} — no retries"),
        Err(FetchError::Exhausted)    => println!("exhausted"),
        Err(e)                        => println!("other: {:?}", e),
    }
}
```

## Common Mistake

Retrying on every `Err` variant — including `Permanent` — without a classify step
burns the retry budget and never recovers.

```rust
for _ in 0..max_retries {
    match t.fetch(url) {
        Ok(r)  => return Ok(r),
        Err(_) => continue, // ✗ retries Permanent(404) forever — no classify, no backoff
    }
}
```
