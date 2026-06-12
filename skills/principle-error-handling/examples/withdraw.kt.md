# Error Handling — Kotlin — Withdraw from Account

## Problem

Kotlin's sealed class hierarchy gives exhaustive `when` matching without checked
exceptions. Returning `Result<Unit>` from `withdraw` keeps the happy path readable
with `fold`, while sealed `WithdrawError` subclasses carry structured fields so callers
can act on `available` balance or frozen state — without any `println` inside the domain.
The caller logs exactly once at the boundary.

## Implementation

```kotlin
// file: account.kt

sealed class WithdrawError(message: String) : Exception(message) {
    class InvalidAmount(val amount: Double)
        : WithdrawError("amount $amount must be positive")
    object AccountFrozen
        : WithdrawError("account is frozen")
    class InsufficientFunds(val available: Double, val requested: Double)
        : WithdrawError("insufficient funds: available=$available requested=$requested")
}

class Account(val id: String, private var balance: Double) {
    private var frozen = false

    fun freeze() { frozen = true }

    fun withdraw(amount: Double): Result<Unit> {
        if (amount <= 0.0)
            return Result.failure(WithdrawError.InvalidAmount(amount))
        if (frozen)
            return Result.failure(WithdrawError.AccountFrozen)
        if (balance < amount)
            return Result.failure(WithdrawError.InsufficientFunds(balance, amount))
        balance -= amount
        return Result.success(Unit)
    }
}
```

```kotlin
// file: main.kt
fun main() {
    val acc = Account("acct-42", 100.0)

    acc.withdraw(150.0).fold(
        onSuccess = { println("withdrawal successful") },
        onFailure = { err ->
            // log ONCE at the boundary with account ID and amount
            System.err.println("[${acc.id}] withdraw 150.0 failed: ${err.message}")
            when (err) {
                is WithdrawError.InvalidAmount    -> System.err.println("hint: amount must be positive")
                is WithdrawError.AccountFrozen    -> System.err.println("hint: contact support to unfreeze")
                is WithdrawError.InsufficientFunds -> System.err.println("hint: available is ${err.available}")
                else                              -> Unit  // unexpected — the log above is sufficient
            }
        }
    )
}
```

## Common Mistake

The domain logs inside `withdraw` AND the result propagates — every layer that also
logs produces duplicate output, burying the root cause in noise.

```kotlin
fun withdraw(amount: Double): Result<Unit> {
    if (balance < amount) {
        println("[WARN] insufficient funds: balance=$balance amount=$amount") // ✗ domain logs
        return Result.failure(WithdrawError.InsufficientFunds(balance, amount)) // ✗ then returns
    }
    // ...
}
```
