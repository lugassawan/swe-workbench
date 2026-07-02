# Factory Method — TypeScript — Notification Channel

## Problem

A notification service must send messages over Email, SMS, or Push depending on a
user preference stored in config. Scattering `new EmailChannel()` at every call site
means adding a new backend requires touching many files. The Factory Method
centralizes construction behind a single function; callers depend only on the
`Channel` interface.

## Implementation

```ts
// file: channel.ts
export interface Channel {
  send(msg: string): void;
}

class EmailChannel implements Channel {
  send(msg: string) { console.log("[email]", msg); }
}
class SmsChannel implements Channel {
  send(msg: string) { console.log("[sms]", msg); }
}
class PushChannel implements Channel {
  send(msg: string) { console.log("[push]", msg); }
}

// Registry-based factory — extend here, nowhere else.
const registry: Record<string, () => Channel> = {
  email: () => new EmailChannel(),
  sms:   () => new SmsChannel(),
  push:  () => new PushChannel(),
};

export function createChannel(kind: string): Channel {
  const factory = registry[kind];
  if (!factory) throw new Error(`Unknown channel: ${kind}`);
  return factory();
}
```

```ts
// file: main.ts
import { createChannel } from "./channel";

for (const kind of ["email", "sms", "push"]) {
  createChannel(kind).send("Your order has shipped.");
}
```

## Common Mistake

Inline `if/else` construction repeated at every call site — adding Push requires
editing every notification function in the codebase.

```ts
// ✗ construction scattered — every call site must repeat this if/else
function notify(kind: string, msg: string) {
  if (kind === "email") new EmailChannel().send(msg);       // ✗ duplicated
  else if (kind === "sms") new SmsChannel().send(msg);     // ✗ duplicated
  // ✗ adding PushChannel requires editing every call site
}
```
