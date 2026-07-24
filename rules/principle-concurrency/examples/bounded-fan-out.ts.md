# Bounded Fan-out — TypeScript — bounded worker pool (p-limit style)

## Problem

Fetch N items concurrently in TypeScript, capping inflight work at K=5 using K async
worker functions that share a mutable `cursor` index. Each worker claims the next index
atomically (`i = cursor++`), fetches, stores into `results[i]`, then loops until the
cursor exceeds the array bounds. `Promise.all(workers)` waits for all K workers to drain
the list. Results land in `results` in original order because each worker writes to its
claimed index slot.

## Implementation

```typescript
// file: bounded-fan-out.ts
async function fetch(id: string): Promise<string> {
  await new Promise((r) => setTimeout(r, 10));
  return `result-${id}`;
}

async function boundedFanOut(ids: string[], K: number): Promise<string[]> {
  const results: string[] = new Array(ids.length);
  let cursor = 0;

  async function worker(): Promise<void> {
    while (true) {
      const i = cursor++; // safe: cursor++ is synchronous; JS only yields at `await`, so no two workers can read the same index
      if (i >= ids.length) break;
      results[i] = await fetch(ids[i]); // write to owned slot
    }
  }

  // Start K workers; each drains ids until none remain.
  await Promise.all(Array.from({ length: K }, worker));
  return results;
}

(async () => {
  const ids = ["a", "b", "c", "d", "e", "f", "g", "h"];
  console.log(await boundedFanOut(ids, 5));
})();
```

## Common Mistake

`Promise.all` over a direct map launches all N promises at once with no cap.

```typescript
// ✗ all N promises are created and started immediately — no worker pool
async function badFanOut(ids: string[]): Promise<string[]> {
  return Promise.all(ids.map(fetch)); // ✗ unbounded inflight
}
```
