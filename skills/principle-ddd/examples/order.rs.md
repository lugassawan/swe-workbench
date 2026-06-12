# Light DDD — Rust — Order Aggregate

## Problem

Rust's ownership model makes the aggregate root pattern a natural fit: private fields
with `&mut self` methods are the only mutation path, so the compiler enforces the sole
entry point rule structurally. `Money` is a value object with `derive(PartialEq, Eq)` —
compared by value, no identity. The same-currency guard in `plus()` is a domain
invariant expressed as a `Result`, not a panic.

## Implementation

```rust
// file: money.rs
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Money { minor_units: i64, currency: String }

impl Money {
    pub fn new(minor_units: i64, currency: &str) -> Self {
        Self { minor_units, currency: currency.to_string() }
    }
    pub fn plus(&self, other: &Money) -> Result<Money, String> {
        if self.currency != other.currency {
            return Err(format!("currency mismatch: {} vs {}", self.currency, other.currency));
        }
        Ok(Money::new(self.minor_units + other.minor_units, &self.currency))
    }
}
```

```rust
// file: order.rs
use crate::money::Money;

#[derive(PartialEq)]
enum Status { Draft, Submitted }

pub struct OrderLine { pub sku: String, pub price: Money }

pub struct Order {
    pub id: String,
    status: Status,
    lines: Vec<OrderLine>,  // private: only mutated through aggregate root methods
}

impl Order {
    pub fn new(id: &str) -> Self {
        Self { id: id.to_string(), status: Status::Draft, lines: Vec::new() }
    }
    pub fn add_line(&mut self, sku: &str, price: Money) -> Result<(), String> {
        if self.status == Status::Submitted {
            return Err("cannot add lines to a submitted order".into());
        }
        self.lines.push(OrderLine { sku: sku.to_string(), price });
        Ok(())
    }
    pub fn submit(&mut self) { self.status = Status::Submitted; }
    pub fn line_count(&self) -> usize { self.lines.len() }
}
```

```rust
// file: repository.rs  (domain-layer port — no implementation)
use crate::order::Order;

pub trait OrderRepository {
    fn find(&self, id: &str) -> Option<Order>;
    fn save(&mut self, order: Order);
}
```

```rust
// file: main.rs
mod money; mod order; mod repository;
use money::Money; use order::Order;

fn main() {
    let mut order = Order::new("ord-1");
    order.add_line("SKU-1", Money::new(1299, "USD")).unwrap();
    order.submit();
    match order.add_line("SKU-2", Money::new(500, "USD")) {
        Ok(())  => println!("added"),
        Err(e)  => println!("rejected: {e}"),  // "rejected: cannot add lines to a submitted order"
    }
}
```

## Common Mistake

Exposing `lines` as `pub` (or returning `&mut Vec<OrderLine>`) lets callers call `.push()`
directly after `submit()`, bypassing the root and silently breaking the invariant.

```rust
pub struct Order {
    pub lines: Vec<OrderLine>,  // ✗ callers can push after submit() — invariant broken
}
```
