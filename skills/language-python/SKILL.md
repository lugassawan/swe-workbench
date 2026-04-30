---
name: language-python
description: Python idioms, error handling, typing, async, and packaging. Auto-load when working with .py/.pyi, pyproject.toml, requirements.txt, setup.py, or mentions of Python, pytest, mypy, asyncio, dataclass, type hints, pydantic.
---
# Python

## Errors are values
- Raise specific exceptions; never `except:`.
- Chain errors: `raise NewError(...) from exc`.
- Inspect via `isinstance`, not message strings.
- Use `contextlib.suppress` for intentional ignores.

```python
from contextlib import suppress

try:
    result = fetch(url)
except httpx.TimeoutException as exc:
    raise ServiceUnavailableError(url) from exc

with suppress(FileNotFoundError):
    cache_path.unlink()
```

## Typing (PEP 484/604)

* Prefer `X | Y` (3.10+); `Optional[X]` only for legacy.
* `TypedDict` for structured dicts (no runtime cost).
* `Protocol` for duck typing (better than ABCs in libs).
* `Final` for constants; `cast` sparingly.

```python
def load(src: str | Path) -> dict[str, int]: ...

class Config(TypedDict):
    host: str
    port: int

class Closeable(Protocol):
    def close(self) -> None: ...

MAX_RETRIES: Final = 3
```
## Dataclasses vs Pydantic vs TypedDict

| Need           | Use                       |
| -------------- | ------------------------- |
| Plain data     | `@dataclass`              |
| Validation/API | `pydantic.BaseModel`      |
| Typed dict     | `TypedDict`               |
| Immutable      | `@dataclass(frozen=True)` |

* Accept `TypedDict`/`Protocol`; return concrete types.
* Use Pydantic for validation/coercion/JSON.

## Async / Await

* No blocking I/O in coroutines → `asyncio.to_thread`.
* Keep task references; avoid orphan tasks.
* Prefer `TaskGroup` (3.11+).
* `TaskGroup` cancels siblings on error; use `gather(..., return_exceptions=True)` if needed.

```python
async def main():
    async with asyncio.TaskGroup() as tg:
        a = tg.create_task(fetch_a())
        b = tg.create_task(fetch_b())
    print(a.result(), b.result())

data = await asyncio.to_thread(blocking_db_query, arg)
```
## Packaging

* Use `src/` layout.
* `pyproject.toml` = single source of truth.
* Editable install: `pip install -e ".[dev]"`.
* Backends: hatchling, setuptools, flit, poetry-core.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-package"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest", "mypy", "ruff"]
```
## Tests

* Prefer fixtures over `setUp/tearDown`.
* Use `@pytest.mark.parametrize`.
* Use `monkeypatch`, `tmp_path` for isolation.
* Register custom marks.

```toml
[tool.pytest.ini_options]
markers = ["integration: slow DB tests"]
```

```python
@pytest.fixture
def client(tmp_path):
    return AppClient(tmp_path / "test.db")

@pytest.mark.parametrize("raw,expected", [
    ("42", 42),
    pytest.param("x", None, id="non-numeric"),
])
def test_parse(raw, expected):
    assert parse_int(raw) == expected

@pytest.mark.integration
def test_real_db(): ...
```
## Linting & Formatting

* `ruff check` + `ruff format`
* `mypy --strict`
* Run both in CI.

## Idioms

* `if x is None` (not falsy checks)
* `field(default_factory=list)` (not mutable defaults)
* `__slots__` for memory-heavy classes
* `@cache` / `@lru_cache` for pure funcs
* Prefer `match` over long `isinstance` chains

## Avoid

* Mutable default args (`def f(x=[])`)
* Bare `except` / swallowing `Exception`
* Unexplained `type: ignore`
* Redundant `@classmethod` factories
* Threads for CPU-bound work (use `ProcessPoolExecutor`)

