---
name: language-python
description: Python idioms, error handling, typing, async, and packaging. Auto-load when working with .py, .pyi files, pyproject.toml, requirements.txt, setup.py, or when the user mentions Python, pytest, mypy, asyncio, dataclass, type hints, or pydantic.
---

# Python

## Errors are values
- Return and raise specific exceptions; never use bare `except:`.
- Chain with `raise NewError("context") from original` to preserve the cause.
- Inspect with `isinstance(exc, SomeError)`; never string-match messages.
- Use `contextlib.suppress(ErrorType)` for intentionally swallowed errors.

```python
try:
    result = fetch(url)
except httpx.TimeoutException as exc:
    raise ServiceUnavailableError(url) from exc

with suppress(FileNotFoundError):
    cache_path.unlink()
```

## Typing — PEP 484 / 604
- Use `X | Y` unions (3.10+); `Optional[X]` only for older targets.
- `TypedDict` for heterogeneous dicts (JSON payloads, config blobs) — zero runtime cost.
- `Protocol` for structural duck-typed interfaces; prefer it over ABCs in library code.
- `Final` for module-level constants; `cast` only to fix type-checker gaps.

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

| Need | Use |
|---|---|
| Plain data container, no validation | `@dataclass` |
| Validated input / API models / settings | `pydantic.BaseModel` |
| Typed dict shape, zero overhead | `TypedDict` |
| Immutable record | `@dataclass(frozen=True)` |

- Accept `TypedDict` / `Protocol` for inputs; return concrete types.
- Reach for Pydantic when you need coercion, validation, or JSON serialisation.

## async / await
- Never call blocking I/O inside a coroutine — use `asyncio.to_thread`.
- Always hold a reference to created tasks; orphaned tasks get GC'd silently.
- Prefer `asyncio.TaskGroup` (3.11+) over `gather` — exceptions propagate immediately.

```python
async def main() -> None:
    async with asyncio.TaskGroup() as tg:
        a = tg.create_task(fetch_a())
        b = tg.create_task(fetch_b())
    print(a.result(), b.result())

data = await asyncio.to_thread(blocking_db_query, arg)
```

## Packaging
- Use `src/` layout — prevents accidental imports from the project root.
- `pyproject.toml` is the single source of truth; avoid `setup.py` in new projects.
- Editable install during development: `pip install -e ".[dev]"`.

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
- Fixtures over `setUp`/`tearDown` — pytest fixtures compose and scope cleanly.
- `@pytest.mark.parametrize` for edge cases; keep each case a plain tuple.
- `monkeypatch` for env vars and imports; `tmp_path` for file system work.
- Mark slow tests so the default suite stays fast.

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

## Idioms cheat sheet
- `if value is None` not `if not value` — avoids falsy surprises.
- Dataclass `field(default_factory=list)` instead of mutable default args.
- `__slots__` on hot dataclasses to cut per-instance memory.
- `@functools.cache` / `@functools.lru_cache` for pure deterministic functions.
- `match` statement (3.10+) over long `isinstance` chains.

## Avoid
- Mutable default arguments (`def f(x=[]):`).
- Catching `Exception` or `BaseException` without re-raising.
- `type: ignore` without a comment explaining why.
- Overusing `@classmethod` factories — prefer `__init__` with `Optional` params.
- Threads for CPU-bound work — use `ProcessPoolExecutor` or a task queue.