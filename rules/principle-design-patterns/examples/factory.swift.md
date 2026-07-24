# Factory Method — Swift — Notification Channel

## Problem

A notification service must deliver messages over Email, SMS, or Push based on a
user's stored preference string. Constructing concrete channel types at every call site
scatters `switch` blocks and forces callers to import implementation modules. A single
factory function owns construction; call sites receive a value conforming to `Channel`
and never reference concrete types.

## Implementation

```swift
// file: Channel.swift
protocol Channel {
    func send(msg: String)
}

struct EmailChannel: Channel {
    func send(msg: String) { print("[email] \(msg)") }
}

struct SmsChannel: Channel {
    func send(msg: String) { print("[sms] \(msg)") }
}

struct PushChannel: Channel {
    func send(msg: String) { print("[push] \(msg)") }
}

// Factory — one switch here, nowhere else.
func makeChannel(kind: String) -> Channel? {
    switch kind {
    case "email": return EmailChannel()
    case "sms":   return SmsChannel()
    case "push":  return PushChannel()
    default:      return nil
    }
}
```

```swift
// file: main.swift
for kind in ["email", "sms", "push"] {
    guard let ch = makeChannel(kind: kind) else {
        print("Unknown channel: \(kind)")
        continue
    }
    ch.send(msg: "Your order has shipped.")
}
```

## Common Mistake

A `switch` repeated at every call site — adding `PushChannel` requires finding and
editing every notification function in the codebase.

```swift
// ✗ construction scattered — every call site must repeat this switch
func notify(kind: String, msg: String) {
    switch kind {
    case "email": EmailChannel().send(msg: msg)   // ✗ duplicated construction
    case "sms":   SmsChannel().send(msg: msg)     // ✗ duplicated construction
    // ✗ adding push requires editing every call site
    default: break
    }
}
```
