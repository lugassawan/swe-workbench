---
name: language-python
description: Python idioms — PEP 8, type hints, dataclasses, context managers, generators, asyncio, and testing. Auto-load when working with .py files, pyproject.toml, requirements.txt, or when the user mentions Python, pytest, asyncio, dataclass, type hints, or virtualenv.
---

# Python

## Type hints
- Annotate all function signatures; `Any` is a smell unless at a genuine boundary.
- Use `dataclass` for data containers with behavior; `TypedDict` for dict-shaped data at boundaries.
- Prefer `Protocol` over ABC when duck typing suffices — no inheritance required.
- `from __future__ import annotations` for forward refs in 3.9 and earlier.

```python
from dataclasses import dataclass, field

@dataclass
class Order:
    id: str
    items: list[str] = field(default_factory=list)
    total: float = 0.0
```

## Errors and exceptions
- Use exceptions for exceptional paths, not flow control.
- Raise specific subclasses; catch the narrowest class you can handle.
- `except Exception:` is almost always wrong — at minimum log and re-raise.
- `contextlib.suppress(SomeError)` for intentional ignore; bare `except:` never.

```python
try:
    result = load(path)
except FileNotFoundError:
    raise MissingConfigError(path) from None
```

## Context managers
- `with` for any resource with a cleanup obligation: files, locks, DB connections.
- `@contextlib.contextmanager` for ad-hoc managers without a full class.
- Never hold a resource longer than the `with` block.

## Generators and iterators
- Prefer generators over materializing full lists when you only iterate once.
- `yield from` to delegate to sub-generators.
- Reach for `itertools` before writing loops: `chain`, `islice`, `groupby`, `product`.

```python
def read_chunks(path: Path, size: int = 4096):
    with open(path, "rb") as f:
        while chunk := f.read(size):
            yield chunk
```

## Concurrency
- **GIL caveat:** threads don't parallelize CPU-bound work — use `ProcessPoolExecutor` or `multiprocessing`.
- `asyncio` for IO-bound concurrency; `asyncio.TaskGroup` (3.11+) for structured fan-out.
- `ThreadPoolExecutor` for legacy sync IO or blocking C extensions.
- One event loop per process; never nest or mix loops.

```python
async def fetch_all(urls: list[str]) -> list[str]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch(u)) for u in urls]
    return [t.result() for t in tasks]
```

## Pattern matching (3.10+)
Use `match` for structural dispatch on data shapes; avoid it as a glorified `if/elif` chain.

```python
match command:
    case {"action": "move", "direction": dir}:
        move(dir)
    case {"action": "quit"}:
        quit()
    case _:
        raise ValueError(f"unknown command: {command}")
```

## Dependencies and packaging
- `pyproject.toml` is the standard — no `setup.py` in new projects.
- `uv` for fast installs; `poetry` for lockfile publishing workflows.
- Pin transitive deps via lockfile (`uv.lock`, `poetry.lock`) in applications; use version ranges in libraries.
- Always isolate with a virtualenv — never install into the system Python.

## Testing
- `pytest` over `unittest` — fixtures, parametrize, and plugins make it richer.
- `@pytest.mark.parametrize` instead of loops inside tests.
- `unittest.mock.patch` for external boundaries only; don't mock internals.
- `pytest-asyncio` for async tests; `respx` or `httpx` mock transport for HTTP clients.

```python
@pytest.mark.parametrize("a, b, expected", [(1, 2, 3), (0, 0, 0)])
def test_add(a, b, expected):
    assert add(a, b) == expected
```

## Performance
- Profile before optimizing: `cProfile` for CPU hotspots, `tracemalloc` for memory.
- `py-spy` samples live processes without code changes.
- C extensions (`cffi`, `Cython`) only after profiling confirms a Python bottleneck.
- Cache attribute lookups in tight loops: `fn = obj.method` outside the loop.

## Avoid
- Mutable default arguments (`def f(x=[])` — use `None`, assign inside).
- `from module import *` — pollutes namespace, breaks static analysis.
- `global` / `nonlocal` except in narrow closures.
- Broad `try/except` blocks that swallow errors silently.
- `subprocess.run(shell=True)` with user-controlled input — use the list form.
- Reimplementing what `itertools`, `functools`, or `collections` already provide.
