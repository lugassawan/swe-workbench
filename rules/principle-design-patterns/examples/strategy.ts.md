# Strategy — TypeScript — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules — percent-off, buy-one-get-one, or no
discount — chosen at runtime from configuration. Embedding the selection logic as an `if/switch`
inside checkout couples the algorithm to its caller. The Strategy pattern replaces branching with
a first-class function; TypeScript's `type DiscountFn` makes this idiom lightweight with no class
hierarchy required.

## Implementation

```ts
// file: discount.ts
export type DiscountFn = (cents: number) => number;

export const percentOff =
  (pct: number): DiscountFn =>
  (cents) =>
    Math.round(cents * (1 - pct / 100));

export const bogo: DiscountFn = (cents) => Math.round(cents / 2);

export const noDiscount: DiscountFn = (cents) => cents;
```

```ts
// file: checkout.ts
import type { DiscountFn } from "./discount";

export function checkout(itemCents: number[], discount: DiscountFn): number {
  const subtotal = itemCents.reduce((sum, c) => sum + c, 0);
  return discount(subtotal);
}
```

```ts
// file: main.ts
import { checkout } from "./checkout";
import { percentOff, bogo, noDiscount } from "./discount";

const items = [1000, 2000, 500]; // 35.00

console.log(checkout(items, percentOff(10))); // 3150 (10% off)
console.log(checkout(items, bogo));           // 1750 (half price)
console.log(checkout(items, noDiscount));     // 3500 (full price)
```

## Common Mistake

Branching on a discount type string inside `checkout` — every new discount type requires
editing `checkout` itself, violating the open/closed principle.

```ts
// ✗ branching on type inside checkout — adding a new discount requires editing checkout
function badCheckout(
  itemCents: number[],
  discountType: "percent" | "bogo" | "none",
  pct?: number,
): number {
  const subtotal = itemCents.reduce((sum, c) => sum + c, 0);
  if (discountType === "percent") {          // ✗ caller must know all variants
    return Math.round(subtotal * (1 - (pct ?? 0) / 100));
  } else if (discountType === "bogo") {      // ✗ edit required per new discount type
    return Math.round(subtotal / 2);
  }
  return subtotal;
}
```
