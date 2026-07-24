# Error Handling — Swift — Withdraw from Account

## Problem

Swift's `throws` + typed `enum Error` make every failure site explicit in the function
signature. A `WithdrawError` enum with associated values for each case — `.invalidAmount`,
`.accountFrozen`, and `.insufficientFunds` — lets callers `catch` each case individually
in a `do/catch` block with pattern matching. The domain never calls `print`; the caller
logs exactly once at the boundary with account ID and amount.

## Implementation

```swift
// file: account.swift
import Foundation

enum WithdrawError: Error {
    case invalidAmount(Double)
    case accountFrozen
    case insufficientFunds(available: Double, requested: Double)
}

extension WithdrawError: CustomStringConvertible {
    var description: String {
        switch self {
        case .invalidAmount(let a):
            return "amount \(a) must be positive"
        case .accountFrozen:
            return "account is frozen"
        case .insufficientFunds(let available, let requested):
            return String(format: "insufficient funds: available=%.2f requested=%.2f",
                          available, requested)
        }
    }
}

struct Account {
    let id: String
    private var balance: Double
    private var frozen: Bool = false

    init(id: String, balance: Double) { self.id = id; self.balance = balance }

    mutating func freeze() { frozen = true }

    mutating func withdraw(amount: Double) throws {
        if amount <= 0      { throw WithdrawError.invalidAmount(amount) }
        if frozen           { throw WithdrawError.accountFrozen }
        if balance < amount { throw WithdrawError.insufficientFunds(available: balance,
                                                                      requested: amount) }
        balance -= amount
    }
}
```

```swift
// file: main.swift
var acc = Account(id: "acct-42", balance: 100.0)

do {
    try acc.withdraw(amount: 150.0)
    print("withdrawal successful")
} catch WithdrawError.accountFrozen {
    // log ONCE at the boundary with account ID and amount
    fputs("[\(acc.id)] withdraw 150.0 failed: account is frozen\n", stderr)
    fputs("hint: contact support to unfreeze\n", stderr)
} catch WithdrawError.insufficientFunds(let available, _) {
    fputs("[\(acc.id)] withdraw 150.0 failed: insufficient funds\n", stderr)
    fputs(String(format: "hint: available balance is %.2f\n", available), stderr)
} catch {
    fputs("[\(acc.id)] withdraw failed: \(error)\n", stderr)
}
```

## Common Mistake

The domain calls `print` before throwing — every layer that also logs the error
produces two outputs per failure, making log correlation impossible.

```swift
mutating func withdraw(amount: Double) throws {
    if balance < amount {
        print("insufficient funds: balance=\(balance)")          // ✗ domain logs
        throw WithdrawError.insufficientFunds(available: balance, // ✗ then throws
                                              requested: amount)
    }
}
```
