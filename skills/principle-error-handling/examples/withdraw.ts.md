# Error Handling — TypeScript — Withdraw from Account

## Problem

TypeScript has no checked exceptions, so thrown errors are `unknown` at catch sites
and callers cannot branch on kind without unsafe narrowing. A discriminated-union
`WithdrawError` returned inside a `Result`-style object makes every failure case
explicit in the return type, forcing callers to handle `invalid_amount`, `frozen`,
and `insufficient_funds` before accessing a successful result — with no `console.log`
inside the domain code.

## Implementation

```typescript
// file: account.ts

export type WithdrawError =
  | { kind: "invalid_amount"; message: string }
  | { kind: "frozen";          message: string }
  | { kind: "insufficient_funds"; message: string; available: number };

type WithdrawResult = { ok: true } | { ok: false; error: WithdrawError };

export class Account {
  readonly id: string;
  private balance: number;
  private frozen: boolean;

  constructor(id: string, balance: number) {
    this.id      = id;
    this.balance = balance;
    this.frozen  = false;
  }

  freeze(): void { this.frozen = true; }

  withdraw(amount: number): WithdrawResult {
    if (amount <= 0) {
      return { ok: false, error: { kind: "invalid_amount",
        message: `amount ${amount} must be positive` } };
    }
    if (this.frozen) {
      return { ok: false, error: { kind: "frozen",
        message: "account is frozen" } };
    }
    if (this.balance < amount) {
      return { ok: false, error: { kind: "insufficient_funds",
        message: `insufficient funds: available ${this.balance}, requested ${amount}`,
        available: this.balance } };
    }
    this.balance -= amount;
    return { ok: true };
  }
}
```

```typescript
// file: main.ts
import { Account } from "./account";

const acc = new Account("acct-42", 100);
const result = acc.withdraw(150);

if (!result.ok) {
  // log ONCE at the boundary with account ID and amount
  console.error(`[${acc.id}] withdraw 150 failed: ${result.error.message}`);
  if (result.error.kind === "insufficient_funds") {
    console.error(`hint: available balance is ${result.error.available}`);
  }
  process.exit(1);
}
console.log("withdrawal successful");
```

## Common Mistake

The domain method calls `console.error` before returning the failure object — every
caller that also logs produces a duplicate entry, making log correlation impossible.

```typescript
withdraw(amount: number): WithdrawResult {
  if (this.balance < amount) {
    console.error(`insufficient funds: ${this.balance}`);         // ✗ domain logs
    return { ok: false, error: { kind: "insufficient_funds",      // ✗ then returns
      message: "insufficient funds", available: this.balance } };
  }
  // ...
}
```
