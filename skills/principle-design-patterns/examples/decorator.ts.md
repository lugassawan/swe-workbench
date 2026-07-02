# Decorator — TypeScript — Retry and Logging Fetch

## Problem

A core HTTP fetch must be augmented with retry logic and request logging. Embedding
both behaviors inside `httpFetch` couples unrelated concerns and makes them
impossible to reuse independently. The Decorator pattern solves this with higher-order
functions: `withRetry` and `withLogging` each wrap a `FetchFn` and return a new
`FetchFn`, composable in any order without touching the core.

## Implementation

```ts
// file: fetcher.ts
export type FetchFn = (url: string) => Promise<string>;

export async function httpFetch(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

export function withRetry(fn: FetchFn, retries: number): FetchFn {
  return async (url) => {
    let lastErr: unknown;
    for (let i = 0; i <= retries; i++) {
      try {
        return await fn(url);
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr;
  };
}

export function withLogging(fn: FetchFn): FetchFn {
  return async (url) => {
    console.log(`[fetch] GET ${url}`);
    try {
      const result = await fn(url);
      console.log(`[fetch] OK ${url}`);
      return result;
    } catch (err) {
      console.error(`[fetch] ERR ${url}:`, err);
      throw err;
    }
  };
}
```

```ts
// file: main.ts
import { httpFetch, withRetry, withLogging } from "./fetcher";

const fetch = withLogging(withRetry(httpFetch, 3));

fetch("https://example.com/api/data").then(console.log);
// [fetch] GET https://example.com/api/data
// [fetch] OK  https://example.com/api/data
```

## Common Mistake

Combining behaviors into a single subclass — adding caching later requires a third
class for every combination already in use.

```ts
// ✗ subclass explosion — every combination requires its own class
class RetryLoggingFetcher {                        // ✗ merged into one
  async fetch(url: string): Promise<string> {      // ✗ retry and logging cannot be reused
    console.log(`[fetch] GET ${url}`);             //   independently
    for (let i = 0; i < 3; i++) {
      try { return await httpFetch(url); }
      catch { /* retry */ }
    }
    throw new Error("all retries failed");
  }
}
// class CachingRetryFetcher { ... }              // ✗ N behaviors → N² classes
```
