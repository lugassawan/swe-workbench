# Observer — Rust — Order Status Notifications

## Problem

An `Order` transitions through statuses — "shipped", "delivered" — and email, SMS, and audit
systems must each react. Rust's trait objects let `Order` hold a `Vec<Box<dyn Observer>>`
without knowing concrete types. Each observer implements a single `Observer` trait; adding a
new channel means writing a new struct and registering it — `Order` is never modified.

## Implementation

```rust
// file: observer.rs
pub trait Observer {
    fn on_status_changed(&self, status: &str);
}

pub struct Order {
    observers: Vec<Box<dyn Observer>>,
    status: String,
}

impl Order {
    pub fn new() -> Self {
        Self { observers: Vec::new(), status: "pending".into() }
    }

    pub fn add_observer(&mut self, observer: Box<dyn Observer>) {
        self.observers.push(observer);
    }

    fn notify(&self) {
        for obs in &self.observers {
            obs.on_status_changed(&self.status);
        }
    }

    pub fn ship(&mut self) {
        self.status = "shipped".into();
        self.notify();
    }

    pub fn deliver(&mut self) {
        self.status = "delivered".into();
        self.notify();
    }
}
```

```rust
// file: main.rs
mod observer;
use observer::{Observer, Order};

struct EmailObserver;
struct SmsObserver;
struct AuditObserver;

impl Observer for EmailObserver {
    fn on_status_changed(&self, status: &str) {
        println!("Email: order is now {status}");
    }
}
impl Observer for SmsObserver {
    fn on_status_changed(&self, status: &str) {
        println!("SMS: order is now {status}");
    }
}
impl Observer for AuditObserver {
    fn on_status_changed(&self, status: &str) {
        println!("Audit: status changed to {status}");
    }
}

fn main() {
    let mut order = Order::new();
    order.add_observer(Box::new(EmailObserver));
    order.add_observer(Box::new(SmsObserver));
    order.add_observer(Box::new(AuditObserver));

    order.ship();
    // Email: order is now shipped
    // SMS: order is now shipped
    // Audit: status changed to shipped
}
```

## Common Mistake

Calling notification services directly from `ship` or `deliver` couples `Order` to every
concrete integration; each new channel requires modifying the domain struct.

```rust
// ✗ Order directly calls services — adding a new notification requires editing Order
pub fn ship(&mut self) {
    self.status = "shipped".into();
    email_service.send("shipped");  // ✗ hard dependency on email_service
    sms_service.send("shipped");    // ✗ hard dependency on sms_service
    // ✗ must edit Order to add audit log
}
```
