# Bounded Fan-out — Python — asyncio.Semaphore + gather

## Problem

Fetch N items concurrently with `asyncio`, capping inflight coroutines at K=5 using
`asyncio.Semaphore`. The `bounded` wrapper acquires the semaphore with `async with sem`
before delegating to `fetch`. `asyncio.gather` launches all wrappers at once — the
semaphore limits how many run concurrently. Results are returned in the same order as the
input list because `gather` preserves submission order.

## Implementation

```python
# file: bounded-fan-out.py
import asyncio

async def fetch(id: str) -> str:
    await asyncio.sleep(0.01)
    return f"result-{id}"

async def main() -> None:
    ids = ["a", "b", "c", "d", "e", "f", "g", "h"]
    K = 5
    sem = asyncio.Semaphore(K)

    async def bounded(id: str) -> str:
        async with sem:           # blocks when K coroutines are already running
            return await fetch(id)

    results = await asyncio.gather(
        *[bounded(id) for id in ids]
    )  # order matches ids; gather preserves submission order
    print(list(results))

asyncio.run(main())
```

## Common Mistake

`gather` over bare `fetch` coroutines starts all N coroutines with no cap.

```python
# ✗ all N coroutines run concurrently — no semaphore, no limit
async def bad_fan_out(ids: list[str]) -> list[str]:
    return list(await asyncio.gather(*[fetch(id) for id in ids]))  # ✗ unbounded
```
