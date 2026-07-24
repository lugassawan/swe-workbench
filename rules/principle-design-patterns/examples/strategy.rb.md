# Strategy — Ruby — Checkout Discount Pricing

## Problem

A checkout must apply a pricing rule chosen at runtime — percent-off, buy-one-get-one, or no
discount. Ruby's Procs and lambdas are first-class callables: each strategy is a lambda that
takes a subtotal in cents and returns the discounted total. `Checkout` accepts any callable,
making new strategies a one-liner addition with zero edits to checkout.

## Implementation

```ruby
# file: discount.rb
module Discount
  PercentOff = ->(pct) { ->(cents) { (cents * (1 - pct / 100.0)).round } }
  Bogo       = ->(cents) { (cents / 2.0).round }
  NoDiscount = ->(cents) { cents }
end
```

```ruby
# file: checkout.rb
class Checkout
  def initialize(discount)
    @discount = discount
  end

  def total(*item_cents)
    subtotal = item_cents.sum
    @discount.call(subtotal)
  end
end
```

```ruby
# file: main.rb
require_relative "discount"
require_relative "checkout"

items = [1000, 2000, 500]  # 35.00

puts Checkout.new(Discount::PercentOff.call(10)).total(*items)  # 3150
puts Checkout.new(Discount::Bogo).total(*items)                 # 1750
puts Checkout.new(Discount::NoDiscount).total(*items)           # 3500
```

## Common Mistake

A `case` branch on a discount-type symbol inside `total` forces a code change every time a
new pricing rule is introduced.

```ruby
# ✗ branching on type inside checkout — adding a new discount requires editing total
class BadCheckout
  def total(*item_cents, discount_type:, pct: 0)
    subtotal = item_cents.sum
    case discount_type                          # ✗ caller must enumerate all variants
    when :percent
      (subtotal * (1 - pct / 100.0)).round      # ✗ algorithm baked into checkout
    when :bogo                                  # ✗ edit required per new discount type
      (subtotal / 2.0).round
    else
      subtotal
    end
  end
end
```
