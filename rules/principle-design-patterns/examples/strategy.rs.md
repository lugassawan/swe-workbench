# Strategy — Rust — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules at runtime — percent-off, buy-one-get-one,
or no discount — chosen from configuration. Idiomatic Rust represents a closed set of variants
with an `enum`; a `match` inside the enum's `apply` method centralises dispatch without heap
allocation. Adding a new variant is a single-site change in the enum, not inside checkout.

## Implementation

```rust
// file: discount.rs
pub enum Discount {
    PercentOff(u32), // discount percentage (0–100)
    Bogo,
    None,
}

impl Discount {
    pub fn apply(&self, cents: u32) -> u32 {
        match self {
            Discount::PercentOff(pct) => cents * (100 - pct) / 100,
            Discount::Bogo => cents / 2,
            Discount::None => cents,
        }
    }
}
```

```rust
// file: checkout.rs
use crate::discount::Discount;

pub struct Checkout {
    pub discount: Discount,
}

impl Checkout {
    pub fn total(&self, item_cents: &[u32]) -> u32 {
        let subtotal: u32 = item_cents.iter().sum();
        self.discount.apply(subtotal)
    }
}
```

```rust
// file: main.rs
mod checkout;
mod discount;

use checkout::Checkout;
use discount::Discount;

fn main() {
    let items = [1000u32, 2000, 500]; // 35.00

    println!("{}", Checkout { discount: Discount::PercentOff(10) }.total(&items)); // 3150
    println!("{}", Checkout { discount: Discount::Bogo }.total(&items));           // 1750
    println!("{}", Checkout { discount: Discount::None }.total(&items));           // 3500
}
```

## Common Mistake

Matching on a discount-type string inside `total` instead of delegating to the enum means
checkout must be edited and re-tested for every new pricing rule.

```rust
// ✗ branching on type inside checkout — adding a new discount requires editing total
pub fn bad_total(item_cents: &[u32], discount_type: &str, pct: u32) -> u32 {
    let subtotal: u32 = item_cents.iter().sum();
    match discount_type {                          // ✗ caller must enumerate all variants
        "percent" => subtotal * (100 - pct) / 100, // ✗ algorithm baked into checkout
        "bogo" => subtotal / 2,                    // ✗ edit required per new discount type
        _ => subtotal,
    }
}
```
