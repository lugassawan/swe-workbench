# Observer — C# — Order Status Notifications

## Problem

An `Order` transitions through statuses — "shipped", "delivered" — and email, SMS, and audit
systems must all react. C#'s native `event Action<string>` makes the Observer pattern a
language primitive: subscribers attach with `+=`, detach with `-=`, and the emitter fires the
event with no knowledge of who is listening. No custom interface or observer list is needed.

## Implementation

```csharp
// file: Order.cs
public class Order
{
    public event Action<string>? StatusChanged;

    public string Status { get; private set; } = "pending";

    public void Ship()
    {
        Status = "shipped";
        StatusChanged?.Invoke(Status);
    }

    public void Deliver()
    {
        Status = "delivered";
        StatusChanged?.Invoke(Status);
    }
}
```

```csharp
// file: Program.cs
var order = new Order();

order.StatusChanged += s => Console.WriteLine($"Email: order is now {s}");
order.StatusChanged += s => Console.WriteLine($"SMS: order is now {s}");
order.StatusChanged += s => Console.WriteLine($"Audit: status changed to {s}");

order.Ship();
// Email: order is now shipped
// SMS: order is now shipped
// Audit: status changed to shipped

order.Deliver();
// Email: order is now delivered
// SMS: order is now delivered
// Audit: status changed to delivered
```

## Common Mistake

Calling `emailService` and `smsService` directly from `Ship()` makes `Order` own every
notification channel; adding audit logging forces an edit to the domain class.

```csharp
// ✗ Order directly calls services — adding a new notification requires editing Order
public void Ship()
{
    Status = "shipped";
    emailService.Send("shipped");   // ✗ hard dependency on EmailService
    smsService.Send("shipped");     // ✗ hard dependency on SmsService
    // ✗ must edit Order to add audit log
}
```
