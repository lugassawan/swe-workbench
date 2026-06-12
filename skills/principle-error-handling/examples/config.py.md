# Error Handling — Python — Config Parse & Validate

## Problem

Python uses exceptions for flow control, so clear error hierarchies matter more than
in languages with typed returns. A `ConfigError` base class with three subclasses
(`IoConfigError`, `ParseConfigError`, `ValidationConfigError`) lets callers catch at
the right granularity and `raise ... from err` preserves the original cause chain.

## Implementation

```python
# file: config.py

class ConfigError(Exception):
    """Base for all config errors."""

class IoConfigError(ConfigError):
    pass

class ParseConfigError(ConfigError):
    def __init__(self, line: int, reason: str):
        super().__init__(f"line {line}: {reason}")
        self.line = line
        self.reason = reason

class ValidationConfigError(ConfigError):
    def __init__(self, field: str, reason: str):
        super().__init__(f"field '{field}': {reason}")
        self.field = field
        self.reason = reason


def parse(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as err:
        raise IoConfigError(f"cannot read '{path}': {err}") from err

    kv: dict[str, str] = {}
    for n, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ParseConfigError(n, "missing '=' separator")
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            raise ParseConfigError(n, "empty key")
        kv[key] = value.strip()

    return validate(kv)


def validate(kv: dict[str, str]) -> dict[str, str]:
    for field in ("host", "port"):
        if field not in kv:
            raise ValidationConfigError(field, "required key missing")
    port_str = kv["port"]
    try:
        port = int(port_str)
    except ValueError as err:
        raise ValidationConfigError("port", f"'{port_str}' is not an integer") from err
    if not 1 <= port <= 65535:
        raise ValidationConfigError("port", f"{port} out of range 1-65535")
    return kv
```

```python
# file: main.py
from config import parse, IoConfigError, ParseConfigError, ValidationConfigError

try:
    cfg = parse("app.conf")
    print(f"host={cfg['host']} port={cfg['port']}")
except IoConfigError as e:
    print(f"IO error: {e}")
except ParseConfigError as e:
    print(f"Parse error at line {e.line}: {e.reason}")
except ValidationConfigError as e:
    print(f"Validation error for '{e.field}': {e.reason}")
```

## Common Mistake

Using a bare `except: pass` — the exception is silently dropped and the caller receives an empty dict with no indication of what went wrong.

```python
try:
    cfg = parse("app.conf")
except:          # ✗ catches everything including KeyboardInterrupt
    pass         # ✗ caller gets nothing; failure is invisible
```
