# Light DDD — Ruby — Order Aggregate

## Problem

Ruby has no built-in value-object construct, so `Money` is a plain class with `attr_reader`,
a custom `==`/`hash`, and `freeze` in the constructor to enforce immutability. The `Order`
aggregate root keeps `@lines` as a private instance variable; `add_line` and `submit` are
the only mutation paths. `OrderRepository` is a module that raises `NotImplementedError` on
every abstract method — a duck-typed port with no infrastructure coupling.

## Implementation

```ruby
# file: money.rb
class Money
  attr_reader :minor_units, :currency

  def initialize(minor_units, currency)
    @minor_units = minor_units
    @currency    = currency
    freeze
  end

  def plus(other)
    raise ArgumentError, "currency mismatch: #{currency} vs #{other.currency}" unless currency == other.currency
    Money.new(minor_units + other.minor_units, currency)
  end

  def ==(other)
    other.is_a?(Money) && minor_units == other.minor_units && currency == other.currency
  end
  alias eql? ==

  def hash
    [minor_units, currency].hash
  end
end
```

```ruby
# file: order.rb
require_relative 'money'

class OrderError < StandardError; end

OrderLine = Struct.new(:sku, :price) do
  def initialize(sku, price) = super.freeze
end

class Order
  attr_reader :id

  def initialize(id)
    @id     = id
    @status = :draft
    @lines  = []
  end

  def add_line(sku, price)
    raise OrderError, "cannot add lines to a submitted order" if @status == :submitted
    @lines << OrderLine.new(sku, price)
  end

  def submit
    @status = :submitted
  end

  def line_count
    @lines.size
  end
end
```

```ruby
# file: order_repository.rb
# Ruby has no interface keyword — this module raises NotImplementedError at call time,
# not load time; callers must override both methods or a runtime error occurs on use.
module OrderRepository
  def find(id)    = raise NotImplementedError
  def save(order) = raise NotImplementedError
end
```

```ruby
# file: main.rb (usage)
require_relative 'money'
require_relative 'order'

order = Order.new("ord-1")
order.add_line("SKU-1", Money.new(1299, "USD"))
order.submit
begin
  order.add_line("SKU-2", Money.new(500, "USD"))
rescue OrderError => e
  puts "rejected: #{e.message}"
  # rejected: cannot add lines to a submitted order
end
```

## Common Mistake

Adding `attr_reader :lines` exposes `@lines` directly; callers can call `.push()` on the
array after `submit`, bypassing the aggregate root and silently breaking the invariant.

```ruby
# file: order.rb (anti-pattern)
attr_reader :lines # ✗ callers can call order.lines.push(...) after submit — invariant broken
```
