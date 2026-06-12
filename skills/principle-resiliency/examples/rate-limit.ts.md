# Resiliency — TypeScript — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd: every client
backs off for the same interval, then fires simultaneously. A token-bucket limiter controls
burst capacity and enforces a steady refill rate. When the bucket is empty the caller backs
off with random jitter instead of retrying at a fixed cadence.

## Implementation

```typescript
// file: rateLimiter.ts
export class TokenBucket {
  private tokens: number;
  private lastRefill: number; // ms

  constructor(
    private readonly capacity: number,
    private readonly refillRatePerMs: number,
  ) {
    this.tokens = capacity;
    this.lastRefill = Date.now();
  }

  tryAcquire(tokens = 1): boolean {
    const now = Date.now();
    const elapsed = now - this.lastRefill;
    this.tokens = Math.min(this.capacity, this.tokens + elapsed * this.refillRatePerMs);
    this.lastRefill = now;
    if (this.tokens >= tokens) {
      this.tokens -= tokens;
      return true;
    }
    return false;
  }
}

export async function callWithRateLimit<T>(
  limiter: TokenBucket,
  operation: () => Promise<T>,
  maxAttempts = 5,
): Promise<T> {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (limiter.tryAcquire()) return operation();
    // Jitter prevents synchronized retries (thundering herd).
    const backoff = 2 ** attempt * (0.5 + Math.random());
    await new Promise((r) => setTimeout(r, backoff));
  }
  throw new Error("rate limit exhausted");
}
```

```typescript
// file: main.ts
import { TokenBucket, callWithRateLimit } from "./rateLimiter";

// 3-token burst, refills 1 token/second
const limiter = new TokenBucket(3, 1 / 1000);

for (let i = 0; i < 5; i++) {
  callWithRateLimit(limiter, async () => `ok-${i}`)
    .then((r) => console.log(r))
    .catch(() => console.log("rejected"));
}
// first 3 succeed immediately; later calls depend on refill timing
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```typescript
class FixedWindowUnsafe {
  private count = 0;
  private windowStart = Date.now();

  tryAcquire(): boolean {
    const now = Date.now();
    if (now - this.windowStart >= this.windowMs) {
      this.count = 0;          // ✗ hard reset enables boundary burst
      this.windowStart = now;
    }
    if (this.count < this.limit) { this.count++; return true; }
    return false;
  }
  constructor(private limit: number, private windowMs: number) {}
}
```
