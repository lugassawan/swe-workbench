# Error Handling — Java — Withdraw from Account

## Problem

Java's checked exceptions force callers to acknowledge failure, but mixing business
errors and programmer errors in a single `Exception` loses the distinction. Three
exception classes — `InvalidAmountException` (unchecked: bad caller input),
`AccountFrozenException`, and `InsufficientFundsException` (both checked: domain state)
— give callers precise `catch` branches. The domain never calls a logger; the caller
logs exactly once at the boundary with account ID and amount.

## Implementation

```java
// file: Account.java
public class Account {

    public static class InvalidAmountException extends IllegalArgumentException {
        public InvalidAmountException(double amount) {
            super(String.format("amount %.2f must be positive", amount));
        }
    }
    public static class AccountFrozenException extends Exception {
        public AccountFrozenException() { super("account is frozen"); }
    }
    public static class InsufficientFundsException extends Exception {
        public final double available;
        public final double requested;
        public InsufficientFundsException(double available, double requested) {
            super(String.format("insufficient funds: available=%.2f requested=%.2f",
                available, requested));
            this.available = available;
            this.requested = requested;
        }
    }

    public final String id;
    private double balance;
    private boolean frozen;

    public Account(String id, double balance) { this.id = id; this.balance = balance; }
    public void freeze() { this.frozen = true; }

    public void withdraw(double amount)
            throws AccountFrozenException, InsufficientFundsException {
        if (amount <= 0) throw new InvalidAmountException(amount);
        if (frozen)      throw new AccountFrozenException();
        if (balance < amount) throw new InsufficientFundsException(balance, amount);
        balance -= amount;
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        var acc = new Account("acct-42", 100.0);
        try {
            acc.withdraw(150.0);
            System.out.println("withdrawal successful");
        } catch (Account.AccountFrozenException e) {
            // log ONCE at the boundary with account ID and amount
            System.err.println("[" + acc.id + "] withdraw 150.00 failed: " + e.getMessage());
            System.err.println("hint: contact support to unfreeze");
        } catch (Account.InsufficientFundsException e) {
            System.err.println("[" + acc.id + "] withdraw 150.00 failed: " + e.getMessage());
            System.err.printf("hint: available balance is %.2f%n", e.available);
        }
    }
}
```

## Common Mistake

The domain calls `logger.warning` before throwing — every layer that also logs the
exception produces duplicate log lines, obscuring which layer owns the failure.

```java
public void withdraw(double amount)
        throws AccountFrozenException, InsufficientFundsException {
    if (balance < amount) {
        System.err.println("insufficient funds: balance=" + balance); // ✗ domain logs
        throw new InsufficientFundsException(balance, amount);        // ✗ then throws
    }
}
```
