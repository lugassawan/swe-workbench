# Light DDD — TypeScript — Order Aggregate

## Problem

TypeScript's `readonly` constructor parameters give `Money` immutable fields
without a separate assignment step, and an explicit `equals()` method handles
value comparison (JS/TS lacks built-in structural equality for class instances).
The `Order` aggregate root guards `private lines: OrderLine[]` behind `addLine`
and `submit`, so no caller can bypass the draft-only invariant. `OrderRepository`
is a plain `interface` — a domain port with zero infrastructure coupling.

## Implementation

```typescript
// file: money.ts
export class Money {
  constructor(
    readonly minorUnits: number,
    readonly currency: string,
  ) {}

  plus(other: Money): Money {
    if (this.currency !== other.currency) {
      throw new Error(`currency mismatch: ${this.currency} vs ${other.currency}`);
    }
    return new Money(this.minorUnits + other.minorUnits, this.currency);
  }

  equals(other: Money): boolean {
    return this.minorUnits === other.minorUnits && this.currency === other.currency;
  }
}
```

```typescript
// file: order.ts
import { Money } from "./money";

type Status = "draft" | "submitted";

export interface OrderLine { readonly sku: string; readonly price: Money }

export class Order {
  private status: Status = "draft";
  private lines: OrderLine[] = [];

  constructor(readonly id: string) {}

  addLine(sku: string, price: Money): void {
    if (this.status === "submitted") {
      throw new Error("cannot add lines to a submitted order");
    }
    this.lines.push({ sku, price });
  }

  submit(): void { this.status = "submitted"; }
  lineCount(): number { return this.lines.length; }
}
```

```typescript
// file: orderRepository.ts
import { Order } from "./order";

export interface OrderRepository {
  find(id: string): Order | undefined;
  save(order: Order): void;
}
```

```typescript
// file: main.ts
import { Money } from "./money";
import { Order } from "./order";

console.log(new Money(1299, "USD").equals(new Money(1299, "USD"))); // true — value equality

const order = new Order("ord-1");
order.addLine("SKU-1", new Money(1299, "USD"));
order.submit();
try {
  order.addLine("SKU-2", new Money(500, "USD"));
} catch (e) {
  console.log(`rejected: ${(e as Error).message}`);
  // rejected: cannot add lines to a submitted order
}
```

## Common Mistake

Declaring `lines` as a `public` field lets any caller call `.push()` directly
after `submit()`, bypassing the aggregate root and silently breaking the invariant.

```typescript
export class Order {
  public lines: OrderLine[] = [];  // ✗ callers can push after submit() — invariant broken
}
```
