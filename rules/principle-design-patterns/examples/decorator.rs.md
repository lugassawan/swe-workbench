# Decorator — Rust — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior without modifying `HttpFetcher`.
Rust's generic wrapper structs implement a `Fetcher` trait and hold an inner `F:
Fetcher`, avoiding heap allocation. `LoggingFetcher<RetryFetcher<HttpFetcher>>`
composes at the type level — behaviors are zero-cost and reusable in any order.

## Implementation

```rust
// file: fetcher.rs
pub trait Fetcher {
    fn fetch(&self, url: &str) -> Result<String, String>;
}

pub struct HttpFetcher;

impl Fetcher for HttpFetcher {
    fn fetch(&self, url: &str) -> Result<String, String> {
        // In real code: use ureq or reqwest.
        Err(format!("not implemented for {url}"))
    }
}

pub struct RetryFetcher<F: Fetcher> {
    pub inner: F,
    pub retries: u32,
}

impl<F: Fetcher> Fetcher for RetryFetcher<F> {
    fn fetch(&self, url: &str) -> Result<String, String> {
        let mut last_err = String::new();
        for _ in 0..=self.retries {
            match self.inner.fetch(url) {
                Ok(body) => return Ok(body),
                Err(e) => last_err = e,
            }
        }
        Err(last_err)
    }
}

pub struct LoggingFetcher<F: Fetcher> {
    pub inner: F,
}

impl<F: Fetcher> Fetcher for LoggingFetcher<F> {
    fn fetch(&self, url: &str) -> Result<String, String> {
        println!("[fetch] GET {url}");
        match self.inner.fetch(url) {
            Ok(body) => {
                println!("[fetch] OK  {url}");
                Ok(body)
            }
            Err(e) => {
                eprintln!("[fetch] ERR {url}: {e}");
                Err(e)
            }
        }
    }
}
```

```rust
// file: main.rs
mod fetcher;
use fetcher::{Fetcher, HttpFetcher, LoggingFetcher, RetryFetcher};

fn main() {
    let fetch = LoggingFetcher {
        inner: RetryFetcher { inner: HttpFetcher, retries: 3 },
    };
    match fetch.fetch("https://example.com/api/data") {
        Ok(body) => println!("{body}"),
        Err(e) => eprintln!("error: {e}"),
    }
}
```

## Common Mistake

Creating a monolithic struct that hardcodes both retry and logging — behaviors are
inseparable and every new combination requires a new struct.

```rust
// ✗ subclass explosion — retry + logging fused into one struct
struct RetryLoggingFetcher {               // ✗ behaviors cannot be used independently
    retries: u32,
}
impl Fetcher for RetryLoggingFetcher {
    fn fetch(&self, url: &str) -> Result<String, String> {
        println!("[fetch] GET {url}");     // ✗ retry always logs; cannot silence
        for _ in 0..=self.retries {
            if let Ok(b) = http_get(url) { return Ok(b); }
        }
        Err("all retries failed".into())
    }
}
// struct CachingRetryFetcher { ... }     // ✗ N behaviors → N² structs
```
