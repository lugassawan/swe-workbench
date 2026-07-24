# Error Handling — Go — Withdraw from Account

## Problem

Go surfaces errors as values; choosing between sentinel errors, typed structs, and
coded fields depends on what callers must branch on. The `withdraw` function returns
a typed `WithdrawError` with a `Code` field — illustrating coded errors — while
sentinel values let callers use `errors.Is` for the two expected domain failures.
The domain never logs; the boundary logs exactly once with account ID and amount.

## Implementation

```go
// file: account.go
package account

import (
	"errors"
	"fmt"
)

var ErrInsufficientFunds = errors.New("insufficient funds")
var ErrAccountFrozen    = errors.New("account frozen")

type WithdrawError struct {
	Code    string
	Amount  float64
	Balance float64
	Err     error
}

func (e *WithdrawError) Error() string {
	return fmt.Sprintf("[%s] amount=%.2f balance=%.2f: %v", e.Code, e.Amount, e.Balance, e.Err)
}
func (e *WithdrawError) Unwrap() error { return e.Err }

type Account struct {
	ID      string
	balance float64
	frozen  bool
}

func New(id string, balance float64) *Account { return &Account{ID: id, balance: balance} }
func (a *Account) Freeze()                    { a.frozen = true }

func (a *Account) Withdraw(amount float64) error {
	if amount <= 0 {
		return &WithdrawError{Code: "INVALID_AMOUNT", Amount: amount, Balance: a.balance,
			Err: fmt.Errorf("amount must be positive")}
	}
	if a.frozen {
		return &WithdrawError{Code: "ACCOUNT_FROZEN", Amount: amount, Balance: a.balance,
			Err: ErrAccountFrozen}
	}
	if a.balance < amount {
		return &WithdrawError{Code: "INSUFFICIENT_FUNDS", Amount: amount, Balance: a.balance,
			Err: ErrInsufficientFunds}
	}
	a.balance -= amount
	return nil
}
```

```go
// file: main.go
package main

import (
	"errors"
	"log"
	"example/account"
)

func main() {
	acc := account.New("acct-42", 100.00)

	err := acc.Withdraw(150.00)
	if err != nil {
		// log ONCE at the boundary with full context
		log.Printf("withdraw failed [%s] amount=150.00: %v", acc.ID, err)

		if errors.Is(err, account.ErrInsufficientFunds) {
			log.Println("hint: reduce withdrawal amount or top up balance")
		} else if errors.Is(err, account.ErrAccountFrozen) {
			log.Println("hint: contact support to unfreeze the account")
		}
		return
	}
	log.Println("withdrawal successful")
}
```

## Common Mistake

Domain code logs before returning the error — every caller that also logs produces
duplicate lines, burying the root cause in noise.

```go
func (a *Account) Withdraw(amount float64) error {
	if a.balance < amount {
		log.Printf("insufficient funds: balance=%.2f amount=%.2f", a.balance, amount) // ✗ domain logs
		return &WithdrawError{Code: "INSUFFICIENT_FUNDS", Err: ErrInsufficientFunds}  // ✗ then returns
	}
	// ...
}
```
