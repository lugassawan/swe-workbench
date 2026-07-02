# Observer — Python — Order Status Notifications

## Problem

An `Order` transitions through statuses — "shipped", "delivered" — and email, SMS, and audit
systems must react independently. Python callables are first-class, so listeners are plain
functions; no class hierarchy is required. `Order` holds a list of `Callable[[str], None]`
and calls each on state change. A `Protocol` documents the expected shape for type-checkers
without adding runtime coupling.

## Implementation

```python
# file: order.py
from __future__ import annotations
from collections.abc import Callable

StatusListener = Callable[[str], None]


class Order:
    def __init__(self) -> None:
        self._listeners: list[StatusListener] = []
        self._status = "pending"

    def add_listener(self, fn: StatusListener) -> None:
        self._listeners.append(fn)

    def _notify(self, status: str) -> None:
        for fn in self._listeners:
            fn(status)

    def ship(self) -> None:
        self._status = "shipped"
        self._notify(self._status)

    def deliver(self) -> None:
        self._status = "delivered"
        self._notify(self._status)
```

```python
# file: main.py
from order import Order

order = Order()

order.add_listener(lambda s: print(f"Email: order is now {s}"))
order.add_listener(lambda s: print(f"SMS: order is now {s}"))
order.add_listener(lambda s: print(f"Audit: status changed to {s}"))

order.ship()
# Email: order is now shipped
# SMS: order is now shipped
# Audit: status changed to shipped

order.deliver()
# Email: order is now delivered
# SMS: order is now delivered
# Audit: status changed to delivered
```

## Common Mistake

Calling `email_service` and `sms_service` directly inside `ship` makes `Order` the integration
point for every channel — adding audit logging means editing the domain class.

```python
# ✗ Order directly calls services — adding a new notification requires editing Order
def ship(self) -> None:
    self._status = "shipped"
    email_service.send("shipped")   # ✗ hard dependency on email_service
    sms_service.send("shipped")     # ✗ hard dependency on sms_service
    # ✗ must edit Order to add audit log
```
