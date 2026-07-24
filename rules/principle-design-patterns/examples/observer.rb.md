# Observer — Ruby — Order Status Notifications

## Problem

An `Order` emits status changes — "shipped", "delivered" — and email, SMS, and audit systems
must all react independently. Ruby's blocks and lambdas are first-class callables: `Order`
stores an array of procs and calls each when the status changes. Listeners are registered with
`add_listener(&block)`, keeping the emitter completely decoupled. Ruby also ships the
`Observable` module in stdlib, but the manual approach shown here is clearer for learning.

## Implementation

```ruby
# file: order.rb
class Order
  def initialize
    @listeners = []
    @status = "pending"
  end

  def add_listener(&block)
    @listeners << block
  end

  def ship
    @status = "shipped"
    notify_listeners
  end

  def deliver
    @status = "delivered"
    notify_listeners
  end

  private

  def notify_listeners
    @listeners.each { |fn| fn.call(@status) }
  end
end
```

```ruby
# file: main.rb
require_relative "order"

order = Order.new

order.add_listener { |s| puts "Email: order is now #{s}" }
order.add_listener { |s| puts "SMS: order is now #{s}" }
order.add_listener { |s| puts "Audit: status changed to #{s}" }

order.ship
# Email: order is now shipped
# SMS: order is now shipped
# Audit: status changed to shipped

order.deliver
# Email: order is now delivered
# SMS: order is now delivered
# Audit: status changed to delivered
```

## Common Mistake

Calling `email_service` and `sms_service` directly from `ship` makes `Order` the owner of
every notification channel; each new integration requires editing the domain class.

```ruby
# ✗ Order directly calls services — adding a new notification requires editing Order
def ship
  @status = "shipped"
  email_service.send("shipped")   # ✗ hard dependency on email_service
  sms_service.send("shipped")     # ✗ hard dependency on sms_service
  # ✗ must edit Order to add audit log
end
```
