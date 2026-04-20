---
name: rust
description: Rust idioms — ownership, borrowing, lifetimes, error handling, traits, and iterators. Auto-load when working with .rs files, Cargo.toml, or when the user mentions Rust, cargo, ownership, borrow checker, trait, lifetime, or async Rust.
---

# Rust

## Ownership in one paragraph
Every value has one owner. Passing by value moves; borrow with `&` (shared, many) or `&mut` (exclusive, one). Shared and mutable references cannot coexist. Most "fights with the borrow checker" are a design smell — the data model mixed ownership and sharing.

## Borrowing rules of thumb
- `&T` when you only read.
- `&mut T` when you mutate in place.
- `T` (by value) when you consume — builders, transforming constructors.
- Return owned types unless the caller clearly benefits from a borrow tied to a parameter's lifetime.

## Lifetimes
- Start without annotations; add them when the compiler asks.
- `'static` does not mean "lives forever" — it means "no non-static references inside". Prefer owned types over `'static` juggling.
- If a struct needs many lifetimes, consider owned data or `Arc` instead.

## Error handling
- Return `Result<T, E>`; use `?` to propagate.
- **Library code:** custom enum with `thiserror`.
- **Application code:** `anyhow::Error` for ergonomics; add context with `.with_context(|| "doing X")`.
- Reserve `panic!` for invariant violations the caller cannot recover from.

```rust
#[derive(thiserror::Error, Debug)]
pub enum LoadError {
    #[error("io: {0}")] Io(#[from] std::io::Error),
    #[error("bad format: {0}")] Format(String),
}
```

## Traits
- Design around capability, not identity (`Read`, not `IsFile`).
- Default methods let traits evolve without breaking implementors.
- `impl Trait` in arguments → static dispatch, monomorphized, fast.
- `dyn Trait` behind `Box`/`&` → dynamic dispatch, smaller binary, one code path.
- Choose `dyn` for open-ended type sets or heterogeneous collections.

## Iterators
Prefer iterator chains over indexed loops — usually faster, always clearer.

```rust
let total: u32 = orders.iter()
    .filter(|o| o.is_paid())
    .map(|o| o.total)
    .sum();
```

- `collect::<Vec<_>>()` only when you need to materialize.
- `iter()` borrows; `into_iter()` consumes; `iter_mut()` mutates in place.

## Avoiding unnecessary clones
- `.clone()` in a hot path is a red flag — can you borrow instead?
- `Cow<'a, str>` for "maybe owned, maybe borrowed" in APIs.
- `Arc<T>` for cheap shared ownership across threads; `Rc<T>` single-threaded.

## Option and Result ergonomics
- `?` propagates.
- `ok_or_else`, `map_err`, `and_then`, `unwrap_or_else` — chain, don't match.
- Reserve `unwrap`/`expect` for truly unreachable cases; always prefer `expect("why")` over `unwrap` in production.

## Testing
- `#[cfg(test)] mod tests { ... }` at the bottom of each file for unit tests.
- Integration tests in `tests/`.
- `#[should_panic(expected = "...")]` for panic paths.
- `cargo test`, `cargo clippy -- -D warnings`, `cargo fmt --check` in CI.

## Async
- Pick one runtime (usually `tokio`) and stay there.
- `async fn` in traits — `async-trait` or the stable equivalent.
- `Send + 'static` bounds propagate; design for them from the start.
- Do not block in async — `spawn_blocking` for CPU or sync IO.

## Avoid
- `unsafe` without a `// SAFETY:` comment explaining the invariant.
- Reimplementing iterators imperatively.
- `String` where `&str` would do for read-only input.
- Deep trait hierarchies — traits compose, they do not inherit.
