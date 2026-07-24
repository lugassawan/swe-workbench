# Strategy — Java — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules at runtime — percent-off, buy-one-get-one,
or no discount — selected from configuration. Hardcoding the selection as a `switch` inside
checkout couples the algorithm to its caller. A `@FunctionalInterface` makes Strategy a single
method; lambda expressions supply each variant without boilerplate class files.

## Implementation

```java
// file: DiscountStrategy.java
@FunctionalInterface
public interface DiscountStrategy {
    /** Returns the discounted price in cents. */
    int apply(int cents);

    static DiscountStrategy percentOff(int pct) {
        return cents -> Math.round(cents * (100 - pct) / 100f);
    }

    static DiscountStrategy bogo() {
        return cents -> cents / 2;
    }

    static DiscountStrategy none() {
        return cents -> cents;
    }
}
```

```java
// file: Checkout.java
import java.util.List;

public final class Checkout {
    private final DiscountStrategy discount;

    public Checkout(DiscountStrategy discount) {
        this.discount = discount;
    }

    public int total(List<Integer> itemCents) {
        int subtotal = itemCents.stream().mapToInt(Integer::intValue).sum();
        return discount.apply(subtotal);
    }
}
```

```java
// file: Main.java
import java.util.List;

public class Main {
    public static void main(String[] args) {
        var items = List.of(1000, 2000, 500); // 35.00

        System.out.println(new Checkout(DiscountStrategy.percentOff(10)).total(items)); // 3150
        System.out.println(new Checkout(DiscountStrategy.bogo()).total(items));         // 1750
        System.out.println(new Checkout(DiscountStrategy.none()).total(items));         // 3500
    }
}
```

## Common Mistake

A `switch` on a discount-type string inside `total` means every new pricing rule requires
editing `Checkout`, which should be closed to modification.

```java
// ✗ branching on type inside checkout — adding a new discount requires editing total
public int badTotal(List<Integer> itemCents, String discountType, int pct) {
    int subtotal = itemCents.stream().mapToInt(Integer::intValue).sum();
    switch (discountType) {                 // ✗ caller must enumerate all variants
        case "percent":                     // ✗ algorithm lives inside checkout
            return Math.round(subtotal * (100 - pct) / 100f);
        case "bogo":                        // ✗ edit required per new discount type
            return subtotal / 2;
        default:
            return subtotal;
    }
}
```
