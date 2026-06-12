# Error Handling — TypeScript — HTTP Fetch with Retry

## Problem

TypeScript discriminated unions make transient-vs-permanent classification a compile-time
concern: the `FetchResult` type forces every caller to narrow the error variant before
using the response. Injecting a `Transport` interface keeps the retry loop testable
without real network I/O.

## Implementation

```typescript
// file: transport.ts
export type FetchResult =
  | { status: number; body: string }
  | { error: "timeout" | "network" | "exhausted"; status?: never };

export interface Transport {
  fetch(url: string): FetchResult;
}

export class FakeTransport implements Transport {
  private attempt = 0;

  fetch(url: string): FetchResult {
    if (url === "/not-found") return { status: 404, body: "Not Found" };
    const a = this.attempt++;
    if (a < 2) return { error: "timeout" };          // transient: attempts 0, 1
    return { status: 200, body: "OK" };               // success: attempt 2+
  }
}
```

```typescript
// file: fetch.ts
import type { FetchResult, Transport } from "./transport";

function isTransient(result: FetchResult): boolean {
  if ("error" in result) return result.error === "timeout" || result.error === "network";
  return result.status >= 500;                        // 5xx
}

function isPermanent(result: FetchResult): boolean {
  if ("error" in result) return false;
  return result.status >= 400 && result.status < 500; // 4xx
}

/**
 * Retries transient failures with exponential backoff + jitter.
 * timeoutMs is modelled as a parameter; real impl passes AbortSignal to fetch().
 */
export function fetchWithRetry(
  transport: Transport,
  url: string,
  maxRetries: number,
  timeoutMs: number,
): FetchResult {
  const BASE_MS = 100;
  let last: FetchResult = { error: "network" };

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const result = transport.fetch(url);

    if (!("error" in result) && result.status < 400) return result;
    if (isPermanent(result)) return result;           // bubble permanent immediately

    last = result;
    const delay = BASE_MS * Math.pow(2, attempt) * (Math.random() * 1.0 + 0.5);
    void delay; // setTimeout(delay) — real impl: await new Promise(r => setTimeout(r, delay))
  }

  return { error: "exhausted" }; // retries consumed; distinct from transient errors
}
```

```typescript
// file: main.ts
import { FakeTransport } from "./transport";
import { fetchWithRetry } from "./fetch";

const t = new FakeTransport();

// transient → success (attempts 0,1 timeout; attempt 2 returns 200)
const r1 = fetchWithRetry(t, "/api/data", 5, 1000);
if ("error" in r1) {
  if (r1.error === "exhausted") {
    console.log("retries consumed — all attempts failed with transient errors");
  } else {
    console.log("transient error:", r1.error);
  }
} else {
  console.log(`status=${r1.status} body=${r1.body}`);
}

// permanent → fail immediately (no retries)
const t2 = new FakeTransport();
const r2 = fetchWithRetry(t2, "/not-found", 5, 1000);
if ("error" in r2) {
  console.log("error:", r2.error);
} else {
  console.log(`permanent status=${r2.status} — returned without retry`);
}
```

## Common Mistake

Retrying all results with no delay and no permanent check turns a 404 into an infinite
spin loop.

```typescript
while (attempts < max) {
  const r = t.fetch(url); // ✗ no classify — retries 404 and auth errors
  if (!("error" in r)) break; // ✗ no backoff — tight loop burns CPU
  attempts++;
}
```
