# Error Handling — Ruby — Withdraw from Account

## Problem

Ruby's exception system is expressive but easy to misuse by rescuing `StandardError`
too broadly. A hierarchy rooted at `WithdrawError < StandardError` with subclasses for
each failure tier lets callers rescue exactly what they can handle. The `withdraw`
method raises typed errors without writing to `$stderr`; the caller logs exactly once
at the boundary with account ID and amount.

## Implementation

```ruby
# file: account.rb

class WithdrawError < StandardError; end

class InvalidAmountError < WithdrawError
  attr_reader :amount
  def initialize(amount)
    super("amount #{amount} must be positive")
    @amount = amount
  end
end

class AccountFrozenError < WithdrawError
  def initialize
    super("account is frozen")
  end
end

class InsufficientFundsError < WithdrawError
  attr_reader :available, :requested
  def initialize(available, requested)
    super("insufficient funds: available=#{format('%.2f', available)} " \
          "requested=#{format('%.2f', requested)}")
    @available = available
    @requested = requested
  end
end

class Account
  attr_reader :account_id

  def initialize(account_id, balance)
    @account_id = account_id
    @balance    = balance
    @frozen     = false
  end

  def freeze!
    @frozen = true
  end

  def withdraw(amount)
    raise InvalidAmountError.new(amount)               if amount <= 0
    raise AccountFrozenError.new                       if @frozen
    raise InsufficientFundsError.new(@balance, amount) if @balance < amount
    @balance -= amount
  end
end
```

```ruby
# file: main.rb
require_relative "account"

acc = Account.new("acct-42", 100.0)

begin
  acc.withdraw(150.0)
  puts "withdrawal successful"
rescue AccountFrozenError => e
  # log ONCE at the boundary with account ID and amount
  $stderr.puts "[#{acc.account_id}] withdraw 150.0 failed: #{e.message}"
  $stderr.puts "hint: contact support to unfreeze"
rescue InsufficientFundsError => e
  $stderr.puts "[#{acc.account_id}] withdraw 150.0 failed: #{e.message}"
  $stderr.puts "hint: available balance is #{format('%.2f', e.available)}"
end
```

## Common Mistake

The domain calls `$stderr.puts` before raising — every layer that also logs the
exception produces duplicate log lines, obscuring which layer owns the failure.

```ruby
def withdraw(amount)
  if @balance < amount
    $stderr.puts "insufficient funds: balance=#{@balance}"        # ✗ domain logs
    raise InsufficientFundsError.new(@balance, amount)            # ✗ then raises
  end
end
```
