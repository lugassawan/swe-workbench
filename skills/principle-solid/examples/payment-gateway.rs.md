# DIP & OCP — Rust — Payment Processing

## Problem
`OrderService` depends on a `PaymentGateway` trait. Rust has no inheritance — polymorphism is
always via traits, either static dispatch (`impl Trait` / generics) or dynamic dispatch
(`Box<dyn Trait>`). Dynamic dispatch is used here so the gateway can be swapped at runtime
(e.g., from config). Adding `PayPalGateway` is a new struct; `OrderService` is never edited
(OCP). The gateway is constructor-injected as `Box<dyn PaymentGateway>` (DIP).

## Implementation

```rust
// file: payment_gateway.rs
pub trait PaymentGateway {
    fn charge(&self, amount_cents: u32, reference: &str) -> bool;
}
```

```rust
// file: stripe_gateway.rs
use crate::payment_gateway::PaymentGateway;

pub struct StripeGateway;

impl PaymentGateway for StripeGateway {
    fn charge(&self, amount_cents: u32, reference: &str) -> bool {
        println!("Stripe: charging {}¢ for {}", amount_cents, reference);
        true
    }
}
```

```rust
// file: paypal_gateway.rs
// Adding PayPal requires no edits to OrderService — this is OCP.
use crate::payment_gateway::PaymentGateway;

pub struct PayPalGateway;

impl PaymentGateway for PayPalGateway {
    fn charge(&self, amount_cents: u32, reference: &str) -> bool {
        println!("PayPal: charging {}¢ for {}", amount_cents, reference);
        true
    }
}
```

```rust
// file: order_service.rs
use crate::payment_gateway::PaymentGateway;

pub struct OrderService {
    gateway: Box<dyn PaymentGateway>, // injected — never constructed here (DIP)
}

impl OrderService {
    pub fn new(gateway: Box<dyn PaymentGateway>) -> Self {
        Self { gateway }
    }

    pub fn place_order(&self, item: &str, amount_cents: u32) -> bool {
        println!("Placing order for \"{}\"", item);
        self.gateway.charge(amount_cents, item)
    }
}
```

```rust
// file: main.rs
mod order_service;
mod payment_gateway;
mod paypal_gateway; // swap `use` below to exercise OCP — no OrderService edits needed
mod stripe_gateway;

use order_service::OrderService;
use stripe_gateway::StripeGateway;
// use paypal_gateway::PayPalGateway; // ← uncomment to swap provider; OrderService unchanged

fn main() {
    // Box<dyn PaymentGateway> is the seam — swap for PayPalGateway; OrderService unchanged (OCP).
    let svc = OrderService::new(Box::new(StripeGateway));
    svc.place_order("widget", 1999);
}
```

## Common Mistake

```rust
// ✗ DIP violation — enum dispatch replaces the trait abstraction; no gateway is injected
// ✗ OCP violation — match arm must be edited for every new provider
enum PaymentMethod { Stripe, PayPal }

struct BadOrderService;

impl BadOrderService {
    fn place_order(&self, item: &str, cents: u32, method: PaymentMethod) -> bool {
        match method {
            PaymentMethod::Stripe => {              // ✗ switch on payment type
                println!("Stripe: charging {}¢", cents); // ✗ logic inline, not abstracted
                true
            }
            PaymentMethod::PayPal => {              // ✗ edit required per new provider
                println!("PayPal: charging {}¢", cents);
                true
            }
        }
    }
}
```
