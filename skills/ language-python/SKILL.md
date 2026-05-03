---
name: language-python
description: Python best practices, typing, async patterns, and packaging conventions
---

## Example

```python
from typing import TypedDict

class User(TypedDict):
    name: str
    age: int

def get_user() -> User:
    return {"name": "Satwik", "age": 20}



## Error Handling

- Use specific exceptions instead of broad `Exception`
- Preserve context with `raise ... from e`
- Avoid catching exceptions unless you can handle them meaningfully
- Prefer context managers for cleanup
- Use `contextlib.suppress` only for narrow, intentional cases

## Typing

- Follow modern typing (PEP 484, PEP 604)
- Prefer `list[str]` over `List[str]`
- Use:
  - `TypedDict` for dict-like structured data
  - `Protocol` for structural typing
  - `Final` for constants
  - `cast()` only when necessary

## Data Modeling

- `dataclasses` → simple, lightweight data containers
- `TypedDict` → JSON-like structures, no behavior
- `pydantic` → validation, parsing, external input

Choose based on:
- Validation needed → Pydantic
- Simplicity → dataclass
- Static typing only → TypedDict

## Async & Concurrency

- Avoid mixing blocking I/O in async functions (use executors if needed)
- Use `asyncio.TaskGroup` for structured concurrency (Python 3.11+)
- Always await created tasks
- Handle cancellation (`asyncio.CancelledError`) explicitly

## Packaging

- Prefer `pyproject.toml` (PEP 517/518) over legacy configs
- Use `src/` layout for packages to avoid import issues
- Use editable installs (`pip install -e .`) during development
- Keep dependencies explicit and minimal

## Testing

- Use `pytest`
- Prefer fixtures over setup/teardown
- Use `@pytest.mark.parametrize` for multiple cases
- Use `monkeypatch` for controlled environment changes
