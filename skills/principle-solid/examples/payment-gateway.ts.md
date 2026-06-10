# DIP & OCP — TypeScript — Payment Processing

## Problem
`OrderService` depends on a `PaymentGateway` interface it owns, never on a concrete class.
TypeScript's structural typing means any object with the right shape satisfies the interface —
no `implements` keyword required, though it's used here for explicitness. Adding `PayPalGateway`
is a new file; `OrderService` is never edited (OCP). The gateway is constructor-injected (DIP).

## Implementation

```ts
// file: payment-gateway.ts
export interface PaymentGateway {
  charge(amountCents: number, reference: string): boolean;
}
```

```ts
// file: stripe-gateway.ts
import type { PaymentGateway } from "./payment-gateway";

export class StripeGateway implements PaymentGateway {
  public charge(amountCents: number, reference: string): boolean {
    console.log(`Stripe: charging ${amountCents}¢ for ${reference}`);
    return true;
  }
}
```

```ts
// file: paypal-gateway.ts
// Adding PayPal requires no edits to OrderService — this is OCP.
import type { PaymentGateway } from "./payment-gateway";

export class PayPalGateway implements PaymentGateway {
  public charge(amountCents: number, reference: string): boolean {
    console.log(`PayPal: charging ${amountCents}¢ for ${reference}`);
    return true;
  }
}
```

```ts
// file: order-service.ts
import type { PaymentGateway } from "./payment-gateway";

export class OrderService {
  public constructor(private readonly gateway: PaymentGateway) {} // injected (DIP)

  public placeOrder(item: string, amountCents: number): boolean {
    console.log(`Placing order for "${item}"`);
    return this.gateway.charge(amountCents, item);
  }
}
```

## Common Mistake

```ts
// ✗ DIP violation — importing a concrete class crosses the abstraction boundary
// ✗ OCP violation — adding PayPal requires editing placeOrder
import Stripe from "stripe"; // ✗ concrete provider dep

export class BadOrderService {
  private stripe = new Stripe(process.env.STRIPE_KEY!);  // ✗ constructed internally

  public placeOrder(item: string, cents: number, method: string): boolean {
    if (method === "stripe") {          // ✗ switch on payment type
      this.stripe.charges.create(...);
    } else if (method === "paypal") {   // ✗ edit required for every new provider
      ...
    }
    return true;
  }
}
```
