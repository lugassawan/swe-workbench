# Strategy — C# — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules at runtime — percent-off, buy-one-get-one,
or no discount — chosen from configuration. C# supports this either through an interface or
a `Func<int, int>` delegate. The interface approach is shown here because it names the abstraction
and is straightforward to mock in tests. `Checkout` receives `IDiscountStrategy` via constructor,
decoupling algorithm selection from checkout logic.

## Implementation

```csharp
// file: IDiscountStrategy.cs
public interface IDiscountStrategy
{
    int Apply(int cents);
}
```

```csharp
// file: Discounts.cs
public sealed class PercentOff(int pct) : IDiscountStrategy
{
    public int Apply(int cents) => (int)Math.Round(cents * (100 - pct) / 100m);
}

public sealed class Bogo : IDiscountStrategy
{
    public int Apply(int cents) => cents / 2;
}

public sealed class NoDiscount : IDiscountStrategy
{
    public int Apply(int cents) => cents;
}
```

```csharp
// file: Checkout.cs
public sealed class Checkout(IDiscountStrategy discount)
{
    public int Total(IEnumerable<int> itemCents)
    {
        int subtotal = itemCents.Sum();
        return discount.Apply(subtotal);
    }
}
```

```csharp
// file: Program.cs
int[] items = [1000, 2000, 500]; // 35.00

Console.WriteLine(new Checkout(new PercentOff(10)).Total(items)); // 3150
Console.WriteLine(new Checkout(new Bogo()).Total(items));          // 1750
Console.WriteLine(new Checkout(new NoDiscount()).Total(items));    // 3500
```

## Common Mistake

A `switch` on a discount-type string inside `Total` means every new pricing rule requires
editing `Checkout`, violating the open/closed principle.

```csharp
// ✗ branching on type inside checkout — adding a new discount requires editing Total
public int BadTotal(IEnumerable<int> itemCents, string discountType, int pct = 0)
{
    int subtotal = itemCents.Sum();
    switch (discountType)                        // ✗ caller must enumerate all variants
    {
        case "percent":                          // ✗ algorithm baked into checkout
            return (int)Math.Round(subtotal * (100 - pct) / 100m);
        case "bogo":                             // ✗ edit required per new discount type
            return subtotal / 2;
        default:
            return subtotal;
    }
}
```
