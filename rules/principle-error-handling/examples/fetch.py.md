# Error Handling — Python — HTTP Fetch with Retry

## Problem

Python's exception hierarchy lets you classify failures by catching the most-specific
subclass first. An abstract `Transport` base class separates the retry policy from
real I/O, and typed `FetchError` subclasses make permanent-vs-transient explicit so
the retry loop never wastes attempts on unrecoverable errors.

## Implementation

```python
# file: transport.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Response:
    status: int
    body: str

class FetchError(Exception): pass
class TransientError(FetchError):
    def __init__(self, status: int):
        super().__init__(f"transient {status}"); self.status = status
class PermanentError(FetchError):
    def __init__(self, status: int):
        super().__init__(f"permanent {status}"); self.status = status
class FetchTimeoutError(FetchError): pass
class ExhaustedError(FetchError): pass

class Transport(ABC):
    @abstractmethod
    def fetch(self, url: str) -> Response: ...


class FakeTransport(Transport):
    def __init__(self) -> None:
        self._attempt = 0

    def fetch(self, url: str) -> Response:
        if url == "/not-found":
            raise PermanentError(404)
        attempt = self._attempt
        self._attempt += 1
        if attempt < 2:
            raise FetchTimeoutError("simulated timeout")
        return Response(status=200, body="OK")
```

```python
# file: fetch.py
import random
from transport import ExhaustedError, FetchError, FetchTimeoutError, PermanentError, Transport, TransientError


def fetch_with_retry(
    transport: Transport,
    url: str,
    max_retries: int,
    timeout_ms: int,  # real impl: passed to requests.get(timeout=timeout_ms/1000)
) -> Response:
    """Retry transient failures with exponential backoff + jitter."""
    BASE_MS = 100
    for attempt in range(max_retries):
        try:
            return transport.fetch(url)
        except PermanentError:
            raise                          # bubble immediately — never retry
        except (TransientError, FetchTimeoutError):
            delay = BASE_MS * (2 ** attempt) * random.uniform(0.5, 1.5)
            _ = delay  # time.sleep(delay / 1000) — real impl uses time.sleep
        except FetchError:
            raise                          # unknown error — bubble

    raise ExhaustedError(f"exhausted {max_retries} retries on {url}")
```

```python
# file: main.py
from transport import FakeTransport, PermanentError
from fetch import ExhaustedError, fetch_with_retry

t = FakeTransport()

# transient → success (attempts 0,1 raise TimeoutError; attempt 2 returns 200)
try:
    resp = fetch_with_retry(t, "/api/data", max_retries=5, timeout_ms=1000)
    print(f"status={resp.status} body={resp.body}")
except ExhaustedError as e:
    print(f"exhausted: {e}")

# permanent → fail immediately
t2 = FakeTransport()
try:
    fetch_with_retry(t2, "/not-found", max_retries=5, timeout_ms=1000)
except PermanentError as e:
    print(f"permanent {e.status} — no retries")
```

## Common Mistake

A bare `except: continue` retries everything, including authentication failures and
bad-request errors that will never succeed.

```python
for _ in range(max_retries):
    try:
        return transport.fetch(url)
    except:          # ✗ catches PermanentError, KeyboardInterrupt, everything
        continue     # ✗ no backoff — tight loop; auth errors retried forever
raise ExhaustedError("exhausted")
```
