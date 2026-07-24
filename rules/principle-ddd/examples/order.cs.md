# Light DDD — C# — Order Aggregate

## Problem

C#'s `readonly record struct` gives `Money` structural equality and immutability with
zero boilerplate — the compiler enforces it. Keeping `_lines` private on `Order` means
`AddLine` and `Submit` are the only mutation paths; the aggregate root invariant is a
naming and access-modifier discipline rather than a compiler guarantee, which makes the
mistake of exposing a public `List<T>` especially easy to commit by accident.

## Implementation

```csharp
// file: Money.cs
public readonly record struct Money(long MinorUnits, string Currency)
{
    public Money Plus(Money other)
    {
        if (Currency != other.Currency)
            throw new ArgumentException(
                $"Currency mismatch: {Currency} vs {other.Currency}");
        return new Money(MinorUnits + other.MinorUnits, Currency);
    }
}
```

```csharp
// file: Order.cs
public record OrderLine(string Sku, Money Price);

public sealed class Order
{
    private enum Status { Draft, Submitted }

    private readonly List<OrderLine> _lines = new();
    private Status _status = Status.Draft;

    public string Id { get; }
    public int LineCount => _lines.Count;

    public Order(string id) => Id = id;

    public void AddLine(string sku, Money price)
    {
        if (_status == Status.Submitted)
            throw new InvalidOperationException(
                "Cannot add lines to a submitted order");
        _lines.Add(new OrderLine(sku, price));
    }

    public void Submit() => _status = Status.Submitted;
}
```

```csharp
// file: IOrderRepository.cs  (domain port only — no implementation)
public interface IOrderRepository
{
    Order? Find(string id);
    void Save(Order order);
}
```

```csharp
// file: Program.cs
var order = new Order("ord-1");
order.AddLine("SKU-1", new Money(1299, "USD"));
order.Submit();
try
{
    order.AddLine("SKU-2", new Money(500, "USD"));
}
catch (InvalidOperationException e)
{
    Console.WriteLine($"rejected: {e.Message}");
    // rejected: Cannot add lines to a submitted order
}
```

## Common Mistake

Exposing lines as a public `List<OrderLine>` property lets any caller call `.Add()`
directly after `Submit()`, bypassing the aggregate root and silently breaking the invariant.

```csharp
public sealed class Order
{
    public List<OrderLine> Lines { get; } = new();  // ✗ callers can .Add() after Submit()
}
```
