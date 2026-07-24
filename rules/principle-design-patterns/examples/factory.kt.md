# Factory Method — Kotlin — Notification Channel

## Problem

A notification service must send messages over Email, SMS, or Push depending on a
user's stored preference. Without a factory, every call site repeats a `when` block
and imports concrete channel types. The Factory Method places that `when` expression in
one top-level function; callers work against the `Channel` interface and never
instantiate channels directly.

## Implementation

```kotlin
// file: Channel.kt
interface Channel {
    fun send(msg: String)
}

object EmailChannel : Channel {
    override fun send(msg: String) = println("[email] $msg")
}

object SmsChannel : Channel {
    override fun send(msg: String) = println("[sms] $msg")
}

object PushChannel : Channel {
    override fun send(msg: String) = println("[push] $msg")
}

// Factory — one when expression, nowhere else.
fun createChannel(kind: String): Channel = when (kind) {
    "email" -> EmailChannel
    "sms"   -> SmsChannel
    "push"  -> PushChannel
    else    -> throw IllegalArgumentException("Unknown channel: $kind")
}
```

```kotlin
// file: main.kt
fun main() {
    listOf("email", "sms", "push").forEach { kind ->
        createChannel(kind).send("Your order has shipped.")
    }
}
```

## Common Mistake

Repeating the `when` block at every call site — adding Push requires editing every
function that constructs channels.

```kotlin
// ✗ construction scattered — every call site must repeat this when block
fun notify(kind: String, msg: String) {
    when (kind) {
        "email" -> EmailChannel.send(msg)   // ✗ duplicated construction
        "sms"   -> SmsChannel.send(msg)     // ✗ duplicated construction
        // ✗ adding push requires editing every call site
    }
}
```
