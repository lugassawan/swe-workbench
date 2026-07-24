# Light DDD — Python — Order Aggregate

## Problem

Python's `@dataclass(frozen=True)` gives `Money` immutability plus structural equality
(`__eq__` and `__hash__` generated from fields) — no manual `__eq__` needed. The `Order`
aggregate root guards its `_lines` list behind `add_line` and `submit`, enforcing the
invariant that lines may not be added once an order is submitted. `Protocol` expresses the
repository port without requiring inheritance.

## Implementation

```python
# file: money.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    minor_units: int
    currency: str

    def plus(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(
                f"currency mismatch: {self.currency} vs {other.currency}"
            )
        return Money(self.minor_units + other.minor_units, self.currency)
```

```python
# file: order.py
from dataclasses import dataclass
from enum import Enum, auto
from money import Money


class _Status(Enum):
    DRAFT = auto()
    SUBMITTED = auto()


@dataclass(frozen=True)
class OrderLine:
    sku: str
    price: Money


class Order:
    def __init__(self, id: str) -> None:
        self.id = id
        self._status = _Status.DRAFT
        self._lines: list[OrderLine] = []

    def add_line(self, sku: str, price: Money) -> None:
        if self._status == _Status.SUBMITTED:
            raise ValueError("cannot add lines to a submitted order")
        self._lines.append(OrderLine(sku, price))

    def submit(self) -> None:
        self._status = _Status.SUBMITTED

    def line_count(self) -> int:
        return len(self._lines)

    def lines(self) -> list[OrderLine]:
        return list(self._lines)  # defensive copy — callers cannot mutate the root
```

```python
# file: order_repository.py
from typing import Optional, Protocol
from order import Order


class OrderRepository(Protocol):
    def find(self, id: str) -> Optional[Order]: ...
    def save(self, order: Order) -> None: ...
```

```python
# file: main.py
from money import Money
from order import Order

order = Order("ord-1")
order.add_line("SKU-1", Money(1299, "USD"))
order.submit()
try:
    order.add_line("SKU-2", Money(500, "USD"))
except ValueError as e:
    print(f"rejected: {e}")
    # rejected: cannot add lines to a submitted order
```

## Common Mistake

Returning `self._lines` directly lets callers call `.append()` on the list, bypassing the
aggregate root and silently breaking the submitted-order invariant.

```python
def lines(self) -> list[OrderLine]:
    return self._lines  # ✗ callers can append after submit() — invariant broken
```
