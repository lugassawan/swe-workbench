# Resiliency — TypeScript — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```typescript
// file: idempotency.ts
type Status = "pending" | "completed";

interface Entry<T> {
  status: Status;
  result?: T;
}

export class IdempotencyStore<T> {
  private store = new Map<string, Entry<T>>();

  async execute(key: string, operation: () => Promise<T>): Promise<T> {
    const existing = this.store.get(key);
    if (existing?.status === "completed") return existing.result as T;
    if (existing?.status === "pending") throw new Error(`key "${key}" already in-flight`);

    // Reserve BEFORE executing — JS event loop: synchronous until the first await,
    // so check+reserve is atomic. Does NOT generalise to multi-threaded runtimes.
    this.store.set(key, { status: "pending" });

    try {
      const result = await operation();
      this.store.set(key, { status: "completed", result });
      return result;
    } catch (e) {
      this.store.delete(key); // release — allows retry with same key
      throw e;
    }
  }
}
```

```typescript
// file: main.ts
import { IdempotencyStore } from "./idempotency";

const store = new IdempotencyStore<{ chargeId: string; amount: number }>();
let calls = 0;

async function charge() {
  calls++;
  return { chargeId: "ch_123", amount: 100 };
}

const key = "order-abc-attempt-1";
const r1 = await store.execute(key, charge);
const r2 = await store.execute(key, charge); // duplicate — returns cached result

console.assert(r1.chargeId === r2.chargeId);
console.assert(calls === 1, `charge executed ${calls} times — expected 1`);
console.log(`chargeId=${r1.chargeId} calls=${calls}`); // chargeId=ch_123 calls=1
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```typescript
async function executeUnsafe<T>(key: string, op: () => Promise<T>): Promise<T> {
  const result = await op();     // ✗ side effect runs first
  store.set(key, result);        // ✗ key recorded after — concurrent retry double-charges
  return result;
}
```
