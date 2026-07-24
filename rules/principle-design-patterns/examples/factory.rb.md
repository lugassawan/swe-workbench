# Factory Method — Ruby — Notification Channel

## Problem

A notification service must send messages over Email, SMS, or Push based on a user's
preference. Instantiating concrete channel classes with `if/case` blocks at each call
site couples callers to implementation classes and scatters construction logic. A
registry-based factory method centralizes that knowledge; call sites receive any object
that responds to `send_message`.

## Implementation

```ruby
# file: channels.rb
class EmailChannel
  def send_message(msg) = puts("[email] #{msg}")
end

class SmsChannel
  def send_message(msg) = puts("[sms] #{msg}")
end

class PushChannel
  def send_message(msg) = puts("[push] #{msg}")
end

# Registry-based factory — one mapping, nowhere else.
CHANNEL_REGISTRY = {
  "email" => EmailChannel,
  "sms"   => SmsChannel,
  "push"  => PushChannel,
}.freeze

def create_channel(kind)
  klass = CHANNEL_REGISTRY.fetch(kind) { raise ArgumentError, "Unknown channel: #{kind}" }
  klass.new
end
```

```ruby
# file: main.rb
require_relative "channels"

%w[email sms push].each do |kind|
  create_channel(kind).send_message("Your order has shipped.")
end
```

## Common Mistake

A `case` expression repeated at every call site — adding `PushChannel` means finding
and editing every place that constructs channels.

```ruby
# ✗ construction scattered — every call site must repeat this case block
def notify(kind, msg)
  case kind
  when "email" then EmailChannel.new.send_message(msg)  # ✗ duplicated
  when "sms"   then SmsChannel.new.send_message(msg)    # ✗ duplicated
  # ✗ adding push requires editing every call site
  end
end
```
