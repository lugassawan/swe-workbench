# Resiliency — Ruby — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```ruby
# file: token_bucket.rb
require 'monitor'

class TokenBucket
  def initialize(capacity:, refill_per_second:)
    @capacity       = capacity.to_f
    @refill_per_s   = refill_per_second.to_f
    @tokens         = @capacity
    @last_refill    = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    @monitor        = Monitor.new
  end

  def try_acquire
    @monitor.synchronize do
      now     = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      elapsed = now - @last_refill
      @tokens = [@capacity, @tokens + elapsed * @refill_per_s].min
      @last_refill = now
      if @tokens >= 1
        @tokens -= 1
        true
      else
        false
      end
    end
  end
end
```

```ruby
# file: main.rb
require_relative 'token_bucket'

bucket = TokenBucket.new(capacity: 3, refill_per_second: 1.0)

def call_with_rate_limit(bucket, max_attempts: 5, &operation)
  max_attempts.times do |attempt|
    return operation.call if bucket.try_acquire
    # Jitter prevents synchronized retries (thundering herd).
    backoff = (2**attempt) * (0.5 + rand)
    sleep(backoff * 0.001)
  end
  raise 'rate limit exhausted'
end

5.times do |i|
  begin
    result = call_with_rate_limit(bucket) { "ok-#{i}" }
    puts result
  rescue RuntimeError
    puts 'rejected'
  end
end
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```ruby
class FixedWindowUnsafe
  def initialize(limit:, window_s:)
    @limit        = limit
    @window_s     = window_s
    @count        = 0
    @window_start = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  end

  def try_acquire
    now = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    if now - @window_start >= @window_s
      @count = 0              # ✗ hard reset enables boundary burst
      @window_start = now
    end
    return false if @count >= @limit
    @count += 1
    true
  end
end
```
