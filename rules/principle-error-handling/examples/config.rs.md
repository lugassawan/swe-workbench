# Error Handling — Rust — Config Parse & Validate

## Problem

Rust's `Result<T, E>` makes the happy path and every failure mode explicit in the
type signature. A typed `enum ConfigError` with distinct variants for IO, parse, and
validation lets callers pattern-match exhaustively, while `?` keeps propagation concise
without hiding which tier the failure came from.

## Implementation

```rust
// file: config.rs
use std::{fmt, fs, io, num::ParseIntError};

#[derive(Debug)]
pub enum ConfigError {
    Io(io::Error),
    Parse { line: usize, reason: String },
    Validation(String),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => write!(f, "io error: {e}"),
            Self::Parse { line, reason } => write!(f, "parse error line {line}: {reason}"),
            Self::Validation(msg) => write!(f, "validation error: {msg}"),
        }
    }
}

impl std::error::Error for ConfigError {}
impl From<io::Error> for ConfigError {
    fn from(e: io::Error) -> Self { Self::Io(e) }
}

pub struct Config { pub host: String, pub port: u16 }

pub fn parse(path: &str) -> Result<Config, ConfigError> {
    let text = fs::read_to_string(path)?; // IO tier — ? converts via From<io::Error>
    let mut kv = std::collections::HashMap::new();

    for (n, line) in text.lines().enumerate().map(|(i, l)| (i + 1, l)) {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') { continue; }
        let (k, v) = line.split_once('=').ok_or_else(|| ConfigError::Parse {
            line: n, reason: "missing '=' separator".into(),
        })?;
        let key = k.trim();
        if key.is_empty() {
            return Err(ConfigError::Parse { line: n, reason: "empty key".into() });
        }
        kv.insert(key.to_string(), v.trim().to_string());
    }
    validate(kv)
}

fn validate(kv: std::collections::HashMap<String, String>) -> Result<Config, ConfigError> {
    let host = kv.get("host").filter(|s| !s.is_empty())
        .ok_or_else(|| ConfigError::Validation("missing required key: host".into()))?
        .clone();
    let port_str = kv.get("port")
        .ok_or_else(|| ConfigError::Validation("missing required key: port".into()))?;
    let port: u16 = port_str.parse().map_err(|_: ParseIntError|
        ConfigError::Validation(format!("port '{}' is not a valid integer 1-65535", port_str)))?;
    if port == 0 {
        return Err(ConfigError::Validation("port must be >= 1".into()));
    }
    Ok(Config { host, port })
}
```

```rust
// file: main.rs
mod config;
use config::ConfigError;

fn main() {
    match config::parse("app.conf") {
        Ok(cfg) => println!("host={} port={}", cfg.host, cfg.port),
        Err(ConfigError::Io(e)) => eprintln!("cannot read file: {e}"),
        Err(ConfigError::Parse { line, reason }) => eprintln!("bad line {line}: {reason}"),
        Err(ConfigError::Validation(msg)) => eprintln!("invalid config: {msg}"),
    }
}
```

## Common Mistake

Calling `.unwrap()` at each step — panics on the first error with no context about which field or line caused it.

```rust
let text = fs::read_to_string(path).unwrap();           // ✗ panics if file missing
let port: u16 = kv["port"].parse().unwrap();            // ✗ panics on non-integer, no line info
```
