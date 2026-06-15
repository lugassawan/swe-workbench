# Error Handling — C# — Withdraw from Account

## Problem

C# exceptions carry an `InnerException` chain and typed subclasses that let callers
`catch` at the right granularity. Three exception classes — `InvalidAmountException`
(unchecked: bad caller input), `AccountFrozenException`, and `InsufficientFundsException`
(domain state) — give callers precise `catch` branches with structured fields like
`Available` and `Requested`. The domain never writes to a logger or console; the caller
logs exactly once at the boundary.

## Implementation

```csharp
// file: Account.cs
using System;

public class InvalidAmountException : ArgumentException {
    public InvalidAmountException(decimal amount)
        : base($"amount {amount:F2} must be positive") { }
}
public class AccountFrozenException : Exception {
    public AccountFrozenException() : base("account is frozen") { }
}
public class InsufficientFundsException : Exception {
    public decimal Available { get; }
    public decimal Requested { get; }
    public InsufficientFundsException(decimal available, decimal requested)
        : base($"insufficient funds: available={available:F2} requested={requested:F2}") {
        Available = available;
        Requested = requested;
    }
}

public class Account {
    public string Id      { get; }
    private decimal balance;
    private bool frozen;

    public Account(string id, decimal balance) { Id = id; this.balance = balance; }
    public void Freeze() { frozen = true; }

    public void Withdraw(decimal amount) {
        if (amount <= 0)        throw new InvalidAmountException(amount);
        if (frozen)             throw new AccountFrozenException();
        if (balance < amount)   throw new InsufficientFundsException(balance, amount);
        balance -= amount;
    }
}
```

```csharp
// file: Program.cs
var acc = new Account("acct-42", 100m);
try {
    acc.Withdraw(150m);
    Console.WriteLine("withdrawal successful");
} catch (AccountFrozenException e) {
    // log ONCE at the boundary with account ID and amount
    Console.Error.WriteLine($"[{acc.Id}] withdraw 150.00 failed: {e.Message}");
    Console.Error.WriteLine("hint: contact support to unfreeze");
} catch (InsufficientFundsException e) {
    Console.Error.WriteLine($"[{acc.Id}] withdraw 150.00 failed: {e.Message}");
    Console.Error.WriteLine($"hint: available balance is {e.Available:F2}");
}
```

## Common Mistake

The domain writes to `Console.Error` before throwing — every layer that also logs the
exception produces duplicate entries, making it impossible to trace which layer owns
the failure.

```csharp
public void Withdraw(decimal amount) {
    if (balance < amount) {
        Console.Error.WriteLine($"insufficient funds: balance={balance}"); // ✗ domain logs
        throw new InsufficientFundsException(balance, amount);             // ✗ then throws
    }
}
```
