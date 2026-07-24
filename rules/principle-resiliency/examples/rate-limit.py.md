# Resiliency — Python — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd: every client
backs off for the same interval, then fires simultaneously. A token-bucket limiter controls
burst capacity and enforces a steady refill rate. When the bucket is empty the caller backs
off with random jitter instead of retrying at a fixed cadence.

## Implementation

```python
# file: rate_limiter.py
import random
import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class TokenBucket:
    capacity: float          # max tokens (burst ceiling)
    refill_rate: float       # tokens per second
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: Lock = field(init=False, default_factory=Lock)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def try_acquire(self, tokens: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._last_refill = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False


def call_with_rate_limit(limiter: TokenBucket, operation, max_attempts: int = 5):
    for attempt in range(max_attempts):
        if limiter.try_acquire():
            return operation()
        # Jitter prevents synchronized retries (thundering herd).
        backoff = (2 ** attempt) * random.uniform(0.5, 1.5)
        time.sleep(backoff * 0.001)  # ms → s (shortened for tests)
    raise RuntimeError("rate limit exhausted")
```

```python
# file: main.py
from rate_limiter import TokenBucket, call_with_rate_limit

limiter = TokenBucket(capacity=3, refill_rate=1.0)
results = []

for i in range(5):
    try:
        result = call_with_rate_limit(limiter, lambda: f"ok-{i}")
        results.append(result)
    except RuntimeError:
        results.append("rejected")

print(results)  # first 3 succeed; remaining depend on refill timing
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries: N requests just
before midnight and N more just after — all within seconds.

```python
class FixedWindowUnsafe:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._count = 0
        self._window_start = time.monotonic()

    def try_acquire(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= self.window_s:
            self._count = 0            # ✗ hard reset enables boundary burst
            self._window_start = now
        if self._count < self.limit:
            self._count += 1
            return True
        return False
```
