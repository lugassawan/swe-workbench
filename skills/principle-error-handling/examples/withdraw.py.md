# Error Handling — Python — Withdraw from Account

## Problem

Python uses exceptions for flow control, so a clear error hierarchy matters more than
in languages with typed returns. A `WithdrawError` base class with subclasses for each
failure — `InvalidAmountError`, `AccountFrozenError`, and `InsufficientFundsError` —
lets callers catch at the right granularity. The `withdraw` method raises typed errors
without calling `logging.error`; the caller logs exactly once at the boundary with
account ID and amount.

## Implementation

```python
# file: account.py

class WithdrawError(Exception):
    """Base for all withdrawal errors."""

class InvalidAmountError(WithdrawError):
    def __init__(self, amount: float):
        super().__init__(f"amount {amount} must be positive")
        self.amount = amount

class AccountFrozenError(WithdrawError):
    def __init__(self):
        super().__init__("account is frozen")

class InsufficientFundsError(WithdrawError):
    def __init__(self, available: float, requested: float):
        super().__init__(
            f"insufficient funds: available={available:.2f} requested={requested:.2f}"
        )
        self.available = available
        self.requested = requested


class Account:
    def __init__(self, account_id: str, balance: float) -> None:
        self.account_id = account_id
        self._balance   = balance
        self._frozen    = False

    def freeze(self) -> None:
        self._frozen = True

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise InvalidAmountError(amount)
        if self._frozen:
            raise AccountFrozenError()
        if self._balance < amount:
            raise InsufficientFundsError(self._balance, amount)
        self._balance -= amount
```

```python
# file: main.py
import logging
from account import Account, AccountFrozenError, InsufficientFundsError

logging.basicConfig(level=logging.INFO)

acc = Account("acct-42", 100.0)

try:
    acc.withdraw(150.0)
    logging.info("withdrawal successful")
except AccountFrozenError as e:
    # log ONCE at the boundary with account ID and amount
    logging.error("withdraw failed [%s] amount=150.0: %s", acc.account_id, e)
    logging.error("hint: contact support to unfreeze")
except InsufficientFundsError as e:
    logging.error("withdraw failed [%s] amount=150.0: %s", acc.account_id, e)
    logging.error("hint: available balance is %.2f", e.available)
```

## Common Mistake

The domain calls `logging.error` then re-raises — every layer that also logs produces
duplicate log entries, burying the root cause in noise.

```python
def withdraw(self, amount: float) -> None:
    if self._balance < amount:
        logging.error("insufficient funds: balance=%.2f", self._balance)  # ✗ domain logs
        raise InsufficientFundsError(self._balance, amount)                # ✗ then raises
```
