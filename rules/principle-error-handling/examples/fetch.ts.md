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
  | { ok: true;  status: number; body: string }
  | { ok: false; error: "timeout" | "network" | "exhausted" | "permanent"; statusCode?: number };

export interface Transport {
  fetch(url: string): FetchResult;
}

export class FakeTransport implements Transport {
  private attempt = 0;

  fetch(url: string): FetchResult {
    if (url === "/not-found") return { ok: false, error: "permanent", statusCode: 404 };
    const a = this.attempt++;
    if (a < 2) return { ok: false, error: "timeout" }; // transient: attempts 0, 1
    return { ok: true, status: 200, body: "OK" };       // success: attempt 2+
  }
}
```

```typescript
// file: fetch.ts
import type { FetchResult, Transport } from "./transport";

function isTransient(result: FetchResult): boolean {
  if (!result.ok) return result.error === "timeout" || result.error === "network";
  return result.status >= 500;                        // 5xx
}

function isPermanent(result: FetchResult): boolean {
  return !result.ok && result.error === "permanent";
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

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const result = transport.fetch(url);

    if (result.ok && result.status < 400) return result;
    if (isPermanent(result)) return result;           // bubble permanent immediately
    if (!isTransient(result)) return result;          // non-transient — bubble

    const delay = BASE_MS * Math.pow(2, attempt) * (Math.random() * 1.0 + 0.5);
    void delay; // real impl: await new Promise(r => setTimeout(r, delay))
  }

  return { ok: false, error: "exhausted" }; // retries consumed; distinct from transient errors
}
```

```typescript
// file: main.ts
import { FakeTransport } from "./transport";
import { fetchWithRetry } from "./fetch";

const t = new FakeTransport();

// transient → success (attempts 0,1 timeout; attempt 2 returns 200)
const r1 = fetchWithRetry(t, "/api/data", 5, 1000);
if (!r1.ok) {
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
if (!r2.ok && r2.error === "permanent") {
  console.log(`permanent ${r2.statusCode} — no retries`);
} else if (!r2.ok) {
  console.log("error:", r2.error);
} else {
  console.log(`unexpected ok: status=${r2.status}`);
}
```

## Common Mistake

Retrying all results with no delay and no permanent check turns a 404 into an infinite
spin loop.

```typescript
while (attempts < max) {
  const r = t.fetch(url);
  if (r.ok) break;                    // ✗ no classify — retries 404 and auth errors
  attempts++;                         // ✗ no backoff — tight loop burns CPU
}
```
