# Strategy — Python — Checkout Discount Pricing

## Problem

A checkout must apply one of several pricing rules at runtime — percent-off, buy-one-get-one,
or no discount — chosen from configuration. Python callables are strategies: a simple closure
or lambda satisfies the contract without a class hierarchy. A `Protocol` documents the expected
shape for type-checkers; plain functions produce strategies at runtime.

## Implementation

```python
# file: discount.py
from typing import Protocol


class Discount(Protocol):
    def __call__(self, cents: int) -> int: ...


def percent_off(pct: float) -> Discount:
    """Return a strategy that takes pct% off the subtotal."""
    def apply(cents: int) -> int:
        return round(cents * (1 - pct / 100))
    return apply


def bogo(cents: int) -> int:
    """Buy-one-get-one: halve the subtotal."""
    return round(cents / 2)


def no_discount(cents: int) -> int:
    """No reduction applied."""
    return cents
```

```python
# file: checkout.py
from collections.abc import Sequence
from discount import Discount


def checkout(item_cents: Sequence[int], discount: Discount) -> int:
    subtotal = sum(item_cents)
    return discount(subtotal)
```

```python
# file: main.py
from checkout import checkout
from discount import percent_off, bogo, no_discount

items = [1000, 2000, 500]  # 35.00

print(checkout(items, percent_off(10)))  # 3150
print(checkout(items, bogo))             # 1750
print(checkout(items, no_discount))      # 3500
```

## Common Mistake

An `if/elif` chain on a discount-type string inside `checkout` must be edited for every new
pricing rule and cannot be extended without touching the caller.

```python
# ✗ branching on type inside checkout — adding a new discount requires editing checkout
def bad_checkout(
    item_cents: list[int],
    discount_type: str,
    pct: float = 0,
) -> int:
    subtotal = sum(item_cents)
    if discount_type == "percent":       # ✗ caller must know all variants
        return round(subtotal * (1 - pct / 100))
    elif discount_type == "bogo":        # ✗ edit required per new discount type
        return round(subtotal / 2)
    return subtotal
```
