# DIP & OCP — C# — Payment Processing

## Problem
`OrderService` depends on an `IPaymentGateway` interface (prefix `I` is the C# convention).
Nullable reference types are enabled — `string reference` is non-nullable by design. Adding
`PayPalGateway` is a new class; `OrderService` is never edited (OCP). The gateway is
constructor-injected, compatible with any DI container like `Microsoft.Extensions.DI` (DIP).

## Implementation

```csharp
// file: IPaymentGateway.cs
public interface IPaymentGateway
{
    bool Charge(int amountCents, string reference);
}
```

```csharp
// file: StripeGateway.cs
public sealed class StripeGateway : IPaymentGateway
{
    public bool Charge(int amountCents, string reference)
    {
        Console.WriteLine($"Stripe: charging {amountCents}¢ for {reference}");
        return true;
    }
}
```

```csharp
// file: PayPalGateway.cs
// Adding PayPal requires no edits to OrderService — this is OCP.
public sealed class PayPalGateway : IPaymentGateway
{
    public bool Charge(int amountCents, string reference)
    {
        Console.WriteLine($"PayPal: charging {amountCents}¢ for {reference}");
        return true;
    }
}
```

```csharp
// file: OrderService.cs
public sealed class OrderService
{
    private readonly IPaymentGateway _gateway; // injected — never newed-up here (DIP)

    public OrderService(IPaymentGateway gateway) => _gateway = gateway;

    public bool PlaceOrder(string item, int amountCents)
    {
        Console.WriteLine($"Placing order for \"{item}\"");
        return _gateway.Charge(amountCents, item);
    }
}
```

## Common Mistake

```csharp
// ✗ DIP violation — OrderService constructs the concrete StripeGateway
// ✗ OCP violation — switch expression must be edited for every new provider
public sealed class BadOrderService
{
    public bool PlaceOrder(string item, int cents, string method) =>
        method switch
        {
            "stripe" => new StripeGateway().Charge(cents, item),  // ✗ newing concrete dep
            "paypal" => new PayPalGateway().Charge(cents, item),  // ✗ edit per new provider
            _ => throw new ArgumentException($"Unknown method: {method}")
        };
}
```
