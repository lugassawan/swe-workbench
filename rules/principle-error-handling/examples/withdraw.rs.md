# Error Handling — Rust — Withdraw from Account

## Problem

Rust's `Result<T, E>` with a typed `enum` error makes every failure path visible in
the function signature and forces exhaustive handling at the call site. The `withdraw`
method carries structured fields (`available`, `requested`) so callers get actionable
data — not just a message — without any logging inside the domain type.
The caller logs exactly once at the boundary with full context.

## Implementation

```rust
// file: account.rs
use std::fmt;

#[derive(Debug)]
pub enum WithdrawError {
    InvalidAmount(f64),
    AccountFrozen,
    InsufficientFunds { available: f64, requested: f64 },
}

impl fmt::Display for WithdrawError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidAmount(a)  => write!(f, "invalid amount: {a:.2} must be positive"),
            Self::AccountFrozen     => write!(f, "account is frozen"),
            Self::InsufficientFunds { available, requested } =>
                write!(f, "insufficient funds: available={available:.2} requested={requested:.2}"),
        }
    }
}

impl std::error::Error for WithdrawError {}

pub struct Account {
    pub id: String,
    balance: f64,
    frozen: bool,
}

impl Account {
    pub fn new(id: &str, balance: f64) -> Self {
        Self { id: id.to_string(), balance, frozen: false }
    }
    pub fn freeze(&mut self) { self.frozen = true; }

    pub fn withdraw(&mut self, amount: f64) -> Result<(), WithdrawError> {
        if amount <= 0.0 {
            return Err(WithdrawError::InvalidAmount(amount));
        }
        if self.frozen {
            return Err(WithdrawError::AccountFrozen);
        }
        if self.balance < amount {
            return Err(WithdrawError::InsufficientFunds {
                available: self.balance,
                requested: amount,
            });
        }
        self.balance -= amount;
        Ok(())
    }
}
```

```rust
// file: main.rs
mod account;
use account::WithdrawError;

fn main() {
    let mut acc = account::Account::new("acct-42", 100.0);

    match acc.withdraw(150.0) {
        Ok(()) => println!("withdrawal successful"),
        Err(e) => {
            // log ONCE at the boundary with account ID and amount
            eprintln!("[{}] withdraw 150.00 failed: {}", acc.id, e);
            match e {
                WithdrawError::InsufficientFunds { available, .. } =>
                    eprintln!("hint: available balance is {available:.2}"),
                WithdrawError::AccountFrozen =>
                    eprintln!("hint: contact support to unfreeze"),
                WithdrawError::InvalidAmount(_) =>
                    eprintln!("hint: amount must be a positive number"),
            }
        }
    }
}
```

## Common Mistake

The domain method calls `eprintln!` before returning `Err` — every layer that also
logs the error produces a duplicate line, making log correlation impossible.

```rust
pub fn withdraw(&mut self, amount: f64) -> Result<(), WithdrawError> {
    if self.balance < amount {
        eprintln!("insufficient funds: {}", self.balance); // ✗ domain logs
        return Err(WithdrawError::InsufficientFunds {      // ✗ then returns error
            available: self.balance, requested: amount,
        });
    }
    // ...
}
```
