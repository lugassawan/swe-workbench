# Resiliency — Python — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent by nature. On network timeout the client
retries, but the server may have already processed the first request. An idempotency-key
dedup store prevents the second execution: reserve the key *before* the side effect, store
the result on completion, and return the stored result on any duplicate.

## Implementation

```python
# file: idempotency.py
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class Status(Enum):
    PENDING = "pending"
    COMPLETED = "completed"


@dataclass
class Entry(Generic[T]):
    status: Status
    result: Optional[T] = None


class IdempotencyStore(Generic[T]):
    def __init__(self) -> None:
        self._store: dict[str, Entry[T]] = {}
        self._lock = Lock()

    def execute(self, key: str, operation: Callable[[], T]) -> T:
        with self._lock:
            entry = self._store.get(key)
            if entry and entry.status == Status.COMPLETED:
                return entry.result  # type: ignore[return-value]
            if entry and entry.status == Status.PENDING:
                raise RuntimeError(f"key {key!r} already in-flight")
            # Reserve BEFORE executing — concurrent retry sees PENDING and stops.
            self._store[key] = Entry(status=Status.PENDING)

        try:
            result = operation()
        except Exception:
            with self._lock:
                del self._store[key]  # release — allows retry with same key
            raise

        with self._lock:
            self._store[key] = Entry(status=Status.COMPLETED, result=result)
        return result
```

```python
# file: main.py
from idempotency import IdempotencyStore

store: IdempotencyStore[dict] = IdempotencyStore()
calls = 0

def charge() -> dict:
    global calls
    calls += 1
    return {"charge_id": "ch_123", "amount": 100}

key = "order-abc-attempt-1"

r1 = store.execute(key, charge)
r2 = store.execute(key, charge)  # duplicate — returns cached result

assert r1 == r2
assert calls == 1, f"charge executed {calls} times — expected 1"
print(f"charge_id={r1['charge_id']} calls={calls}")  # charge_id=ch_123 calls=1
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```python
def execute_unsafe(key: str, operation: Callable[[], T]) -> T:
    result = operation()          # ✗ side effect runs first
    store[key] = result           # ✗ key recorded after — concurrent retry double-charges
    return result
```
