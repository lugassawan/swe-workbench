# Caching — Python — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```python
# file: cache_aside.py
import asyncio
import time
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

V = TypeVar("V")


class CacheAside:
    """Cache-aside with per-key asyncio.Lock for single-flight on cold/expired keys."""

    def __init__(self, ttl: float, loader: Callable[[str], Awaitable[object]]) -> None:
        self._ttl = ttl
        self._loader = loader
        self._store: dict[str, tuple[object, float]] = {}
        # defaultdict(asyncio.Lock) is safe only inside a single-threaded event loop —
        # defaultdict's __missing__ is not thread-safe, so concurrent threads can create
        # duplicate locks for the same key. If you run the loop in a thread pool
        # (e.g. via run_in_executor), guard _locks creation with a threading.Lock instead.
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def get(self, key: str) -> object:
        entry = self._store.get(key)
        if entry and time.monotonic() < entry[1]:
            return entry[0]

        async with self._locks[key]:
            # Re-check after acquiring the lock — another coroutine may have already populated it.
            entry = self._store.get(key)
            if entry and time.monotonic() < entry[1]:
                return entry[0]

            value = await self._loader(key)
            self._store[key] = (value, time.monotonic() + self._ttl)
            return value
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```python
# ✗ no lock — concurrent coroutines all miss and call the loader simultaneously
entry = self._store.get(key)
if entry and time.monotonic() < entry[1]:
    return entry[0]
value = await self._loader(key)  # ✗ stampede: N coroutines all call loader for the same key
self._store[key] = (value, time.monotonic() + self._ttl)
return value
```
