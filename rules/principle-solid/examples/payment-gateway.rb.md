# DIP & OCP — Ruby — Payment Processing

## Problem
Ruby is duck-typed: any object responding to `charge` satisfies the `PaymentGateway` contract.
An abstract base class (using `raise NotImplementedError`) documents intent but is optional —
the duck type is the real contract. Adding `PayPalGateway` is a new file; `OrderService` is
never edited (OCP). The gateway is injected at `initialize` time (DIP).

## Implementation

```ruby
# file: payment_gateway.rb
# Abstract base documents the expected interface; Ruby does not enforce it at runtime.
class PaymentGateway
  def charge(amount_cents, reference)
    raise NotImplementedError, "#{self.class}#charge not implemented"
  end
end
```

```ruby
# file: stripe_gateway.rb
require_relative "payment_gateway"

class StripeGateway < PaymentGateway
  def charge(amount_cents, reference)
    puts "Stripe: charging #{amount_cents}¢ for #{reference}"
    true
  end
end
```

```ruby
# file: paypal_gateway.rb
# Adding PayPal requires no edits to OrderService — this is OCP.
require_relative "payment_gateway"

class PayPalGateway < PaymentGateway
  def charge(amount_cents, reference)
    puts "PayPal: charging #{amount_cents}¢ for #{reference}"
    true
  end
end
```

```ruby
# file: order_service.rb
class OrderService
  def initialize(gateway) # injected — never constructed here (DIP)
    @gateway = gateway
  end

  def place_order(item, amount_cents)
    puts "Placing order for #{item.inspect}"
    @gateway.charge(amount_cents, item)
  end
end
```

## Common Mistake

```ruby
# ✗ DIP violation — OrderService constructs StripeGateway directly
# ✗ OCP violation — case statement must be edited for every new provider
require_relative "stripe_gateway"
require_relative "paypal_gateway"

class BadOrderService
  def place_order(item, cents, method)
    case method                                    # ✗ switch on payment type
    when :stripe
      StripeGateway.new.charge(cents, item)        # ✗ concrete dep newed inline
    when :paypal                                   # ✗ edit required per new provider
      PayPalGateway.new.charge(cents, item)
    end
  end
end
```
