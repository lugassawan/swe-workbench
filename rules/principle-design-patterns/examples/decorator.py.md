# Decorator — Python — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior without embedding those concerns
inside `http_fetch`. Python's decorator syntax is the language-native expression of
the Decorator pattern: `@retry(3)` and `@log_fetch` each wrap the function,
independently reusable, stackable in any order, and the core function is never
modified.

## Implementation

```python
# file: fetcher.py
import functools
import logging
import urllib.request

logger = logging.getLogger(__name__)


def retry(n: int):
    """Decorator factory: retry the wrapped function up to n times on exception."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: BaseException | None = None
            for _ in range(n + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


def log_fetch(fn):
    """Decorator: log each fetch attempt and its outcome."""
    @functools.wraps(fn)
    def wrapper(url: str) -> str:
        logger.info("[fetch] GET %s", url)
        try:
            result = fn(url)
            logger.info("[fetch] OK  %s", url)
            return result
        except Exception as exc:
            logger.error("[fetch] ERR %s: %s", url, exc)
            raise
    return wrapper


@retry(3)
@log_fetch
def http_fetch(url: str) -> str:
    with urllib.request.urlopen(url) as resp:  # noqa: S310
        return resp.read().decode()
```

```python
# file: main.py
import logging
from fetcher import http_fetch

logging.basicConfig(level=logging.INFO)
print(http_fetch("https://example.com/api/data"))
```

## Common Mistake

Defining a combined function that merges retry and logging — the behaviors cannot be
applied separately, and every new combination needs its own function.

```python
# ✗ subclass explosion — retry and logging fused into one function
def retry_logging_fetch(url: str, retries: int = 3) -> str:  # ✗ inseparable behaviors
    print(f"[fetch] GET {url}")                               # ✗ cannot retry silently
    for _ in range(retries + 1):
        try:
            return http_get(url)
        except Exception:
            pass
    raise RuntimeError("all retries failed")
# ✗ adding caching requires retry_logging_caching_fetch, retry_caching_fetch, …
```
