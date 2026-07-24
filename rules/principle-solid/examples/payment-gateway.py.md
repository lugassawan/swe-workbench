# DIP & OCP — Python — Payment Processing

## Problem
`OrderService` must charge payments without knowing which provider is active. Python
expresses the abstraction either as an `ABC` (runtime-enforced) or a structural `Protocol`
(duck-typed, preferred with `mypy`). New providers are new files — `OrderService` is never
touched (OCP). The gateway is injected at construction (DIP).

## Implementation

```python
# file: payment_gateway.py
from typing import Protocol


class PaymentGateway(Protocol):
    def charge(self, amount_cents: int, reference: str) -> bool: ...
```

```python
# file: stripe_gateway.py
class StripeGateway:
    def charge(self, amount_cents: int, reference: str) -> bool:
        print(f"Stripe: charging {amount_cents}¢ for {reference}")
        return True
```

```python
# file: paypal_gateway.py
# Adding PayPal requires no edits to OrderService — this is OCP.
class PayPalGateway:
    def charge(self, amount_cents: int, reference: str) -> bool:
        print(f"PayPal: charging {amount_cents}¢ for {reference}")
        return True
```

```python
# file: order_service.py
from payment_gateway import PaymentGateway


class OrderService:
    def __init__(self, gateway: PaymentGateway) -> None:
        self._gateway = gateway  # injected — never constructed here (DIP)

    def place_order(self, item: str, amount_cents: int) -> bool:
        print(f"Placing order for {item!r}")
        return self._gateway.charge(amount_cents, item)
```

## Common Mistake

```python
# ✗ DIP violation — OrderService owns the concrete dependency
# ✗ OCP violation — adding PayPal requires editing this method
import stripe  # type: ignore

class BadOrderService:
    def place_order(self, item: str, amount_cents: int, method: str) -> bool:
        if method == "stripe":                    # ✗ switch on type
            stripe.Charge.create(amount=amount_cents, currency="usd")
        elif method == "paypal":                  # ✗ edit required for every new provider
            ...
        return True
```
