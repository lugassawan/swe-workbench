# Factory Method — C# — Notification Channel

## Problem

A notification service must deliver messages over Email, SMS, or Push depending on a
user preference. Newing up concrete channel types at each call site scatters the
selection switch across the codebase and forces every caller to import implementation
types. `ChannelFactory.Create` centralizes all construction; callers depend only on the
`IChannel` interface.

## Implementation

```csharp
// file: IChannel.cs
public interface IChannel
{
    void Send(string msg);
}
```

```csharp
// file: Channels.cs
public class EmailChannel : IChannel
{
    public void Send(string msg) => Console.WriteLine($"[email] {msg}");
}

public class SmsChannel : IChannel
{
    public void Send(string msg) => Console.WriteLine($"[sms] {msg}");
}

public class PushChannel : IChannel
{
    public void Send(string msg) => Console.WriteLine($"[push] {msg}");
}
```

```csharp
// file: ChannelFactory.cs
public static class ChannelFactory
{
    // One switch here, nowhere else.
    public static IChannel Create(string kind) => kind switch
    {
        "email" => new EmailChannel(),
        "sms"   => new SmsChannel(),
        "push"  => new PushChannel(),
        _       => throw new ArgumentException($"Unknown channel: {kind}")
    };
}
```

```csharp
// file: Program.cs
foreach (var kind in new[] { "email", "sms", "push" })
{
    ChannelFactory.Create(kind).Send("Your order has shipped.");
}
```

## Common Mistake

A `switch` expression at every call site — adding `PushChannel` requires updating every
notification method across the codebase.

```csharp
// ✗ construction scattered — every call site must repeat this switch
void Notify(string kind, string msg)
{
    IChannel ch = kind switch
    {
        "email" => new EmailChannel(),   // ✗ duplicated construction
        "sms"   => new SmsChannel(),     // ✗ duplicated construction
        // ✗ adding push requires editing every call site
        _       => throw new ArgumentException(kind)
    };
    ch.Send(msg);
}
```
