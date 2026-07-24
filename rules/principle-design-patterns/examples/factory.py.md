# Factory Method — Python — Notification Channel

## Problem

A notification service must route messages to Email, SMS, or Push based on a user's
configuration. Constructing channels inline at every call site repeats the same
`if/elif` logic everywhere. The Factory Method centralizes that logic: a single
`create_channel` function owns all construction; call sites receive a `Channel` and
never import concrete classes.

## Implementation

```python
# file: channel.py
from typing import Protocol


class Channel(Protocol):
    def send(self, msg: str) -> None: ...


class EmailChannel:
    def send(self, msg: str) -> None:
        print(f"[email] {msg}")


class SmsChannel:
    def send(self, msg: str) -> None:
        print(f"[sms] {msg}")


class PushChannel:
    def send(self, msg: str) -> None:
        print(f"[push] {msg}")


# Registry-based factory — one mapping, no scattered switches.
_REGISTRY: dict[str, type[Channel]] = {
    "email": EmailChannel,
    "sms":   SmsChannel,
    "push":  PushChannel,
}


def create_channel(kind: str) -> Channel:
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"Unknown channel: {kind!r}")
    return cls()
```

```python
# file: main.py
from channel import create_channel

for kind in ("email", "sms", "push"):
    create_channel(kind).send("Your order has shipped.")
```

## Common Mistake

An `if/elif` chain at every call site — adding a Push channel requires editing every
place in the codebase that constructs channels.

```python
# ✗ construction scattered — every call site must repeat this if/elif
def notify(kind: str, msg: str) -> None:
    if kind == "email":
        EmailChannel().send(msg)       # ✗ duplicated construction
    elif kind == "sms":
        SmsChannel().send(msg)         # ✗ duplicated construction
    # ✗ adding PushChannel requires editing every call site
```
