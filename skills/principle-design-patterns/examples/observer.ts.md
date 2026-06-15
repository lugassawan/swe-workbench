# Observer — TypeScript — Order Status Notifications

## Problem

An `Order` transitions through statuses — "processing", "shipped", "delivered" — and multiple
independent systems must react: email, SMS, and audit log. Hardwiring those calls into `Order`
creates direct dependencies on every notification channel. The Observer pattern decouples the
emitter from its listeners; `Order` fires an event and knows nothing about who receives it.

## Implementation

```ts
// file: order.ts
export type StatusListener = (status: string) => void;

export class Order {
  private listeners: StatusListener[] = [];
  private status = "pending";

  addListener(fn: StatusListener): void {
    this.listeners.push(fn);
  }

  private notifyAll(status: string): void {
    for (const fn of this.listeners) fn(status);
  }

  ship(): void {
    this.status = "shipped";
    this.notifyAll(this.status);
  }

  deliver(): void {
    this.status = "delivered";
    this.notifyAll(this.status);
  }
}
```

```ts
// file: main.ts
import { Order } from "./order";

const order = new Order();

order.addListener((s) => console.log(`Email: order is now ${s}`));
order.addListener((s) => console.log(`SMS: order is now ${s}`));
order.addListener((s) => console.log(`Audit: status changed to ${s}`));

order.ship();
// Email: order is now shipped
// SMS: order is now shipped
// Audit: status changed to shipped

order.deliver();
// Email: order is now delivered
// SMS: order is now delivered
// Audit: status changed to delivered
```

## Common Mistake

Calling each notification service directly from `Order` makes adding a new channel require
editing the `Order` class itself — a clear violation of the open/closed principle.

```ts
// ✗ Order directly calls services — adding a new notification requires editing Order
class Order {
  ship() {
    emailService.send("shipped");   // ✗ hard dependency on EmailService
    smsService.send("shipped");     // ✗ hard dependency on SmsService
    // ✗ must edit Order to add audit log
  }
}
```
