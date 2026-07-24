# Factory Method — Java — Notification Channel

## Problem

A notification service must dispatch messages over Email, SMS, or Push depending on a
user preference. Instantiating concrete channel classes at every call site duplicates
the selection switch and couples callers to implementation types. The Factory Method
concentrates construction in `ChannelFactory.create`; every caller depends only on the
`Channel` interface.

## Implementation

```java
// file: Channel.java
public interface Channel {
    void send(String msg);
}
```

```java
// file: EmailChannel.java
public class EmailChannel implements Channel {
    public void send(String msg) { System.out.println("[email] " + msg); }
}
```

```java
// file: SmsChannel.java
public class SmsChannel implements Channel {
    public void send(String msg) { System.out.println("[sms] " + msg); }
}
```

```java
// file: PushChannel.java
public class PushChannel implements Channel {
    public void send(String msg) { System.out.println("[push] " + msg); }
}
```

```java
// file: ChannelFactory.java
public class ChannelFactory {
    // One switch here, nowhere else.
    public static Channel create(String kind) {
        return switch (kind) {
            case "email" -> new EmailChannel();
            case "sms"   -> new SmsChannel();
            case "push"  -> new PushChannel();
            default      -> throw new IllegalArgumentException("Unknown channel: " + kind);
        };
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        for (String kind : new String[]{"email", "sms", "push"}) {
            ChannelFactory.create(kind).send("Your order has shipped.");
        }
    }
}
```

## Common Mistake

A repeated `switch` at every call site — adding `PushChannel` means hunting down and
editing every notification method individually.

```java
// ✗ construction scattered — every call site must repeat this switch
void notify(String kind, String msg) {
    switch (kind) {
        case "email" -> new EmailChannel().send(msg);  // ✗ duplicated
        case "sms"   -> new SmsChannel().send(msg);    // ✗ duplicated
        // ✗ adding push requires editing every call site
    }
}
```
