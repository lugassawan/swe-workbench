# Factory Method — Rust — Notification Channel

## Problem

A notification service must send messages over Email, SMS, or Push depending on a
string from user configuration. Without a factory, every caller must `match` on the
kind string and construct the concrete type directly, scattering construction across
the codebase. `create_channel` centralizes that `match`; callers receive a
`Box<dyn Channel>` and remain ignorant of concrete types.

## Implementation

```rust
// file: channel.rs
pub trait Channel {
    fn send(&self, msg: &str);
}

pub struct EmailChannel;
pub struct SmsChannel;
pub struct PushChannel;

impl Channel for EmailChannel {
    fn send(&self, msg: &str) { println!("[email] {}", msg); }
}
impl Channel for SmsChannel {
    fn send(&self, msg: &str) { println!("[sms] {}", msg); }
}
impl Channel for PushChannel {
    fn send(&self, msg: &str) { println!("[push] {}", msg); }
}

// Factory — one match here, nowhere else.
pub fn create_channel(kind: &str) -> Result<Box<dyn Channel>, String> {
    match kind {
        "email" => Ok(Box::new(EmailChannel)),
        "sms"   => Ok(Box::new(SmsChannel)),
        "push"  => Ok(Box::new(PushChannel)),
        other   => Err(format!("unknown channel: {other}")),
    }
}
```

```rust
// file: main.rs
mod channel;
use channel::create_channel;

fn main() {
    for kind in ["email", "sms", "push"] {
        match create_channel(kind) {
            Ok(ch) => ch.send("Your order has shipped."),
            Err(e) => eprintln!("error: {e}"),
        }
    }
}
```

## Common Mistake

A `match` repeated at every call site — adding `PushChannel` requires updating every
notification function individually.

```rust
// ✗ construction scattered — every call site must repeat this match
fn notify(kind: &str, msg: &str) {
    match kind {
        "email" => EmailChannel{}.send(msg),   // ✗ duplicated construction
        "sms"   => SmsChannel{}.send(msg),     // ✗ duplicated construction
        // ✗ adding push requires editing every call site
        _ => {}
    }
}
```
