# Resiliency — Ruby — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```ruby
# file: idempotency.rb
require 'monitor'

class IdempotencyStore
  PENDING   = :pending
  COMPLETED = :completed

  Entry = Struct.new(:status, :result)

  def initialize
    @store = {}
    @monitor = Monitor.new
  end

  def execute(key, &operation)
    @monitor.synchronize do
      entry = @store[key]
      return entry.result if entry&.status == COMPLETED
      raise "key '#{key}' already in-flight" if entry&.status == PENDING

      # Reserve BEFORE executing — concurrent retry sees PENDING and stops.
      @store[key] = Entry.new(PENDING, nil)
    end

    begin
      result = operation.call
    rescue
      @monitor.synchronize { @store.delete(key) }  # release — allows retry
      raise
    end

    @monitor.synchronize { @store[key] = Entry.new(COMPLETED, result) }
    result
  end
end
```

```ruby
# file: main.rb
require_relative 'idempotency'

store = IdempotencyStore.new
calls = 0

charge = -> { calls += 1; { charge_id: 'ch_123', amount: 100 } }

key = 'order-abc-attempt-1'
r1 = store.execute(key, &charge)
r2 = store.execute(key, &charge) # duplicate — returns cached result

raise 'results differ' unless r1 == r2
raise "charge executed #{calls} times — expected 1" unless calls == 1
puts "charge_id=#{r1[:charge_id]} calls=#{calls}" # charge_id=ch_123 calls=1
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```ruby
def execute_unsafe(key, &op)
  result = op.call          # ✗ side effect runs first
  @store[key] = result      # ✗ key recorded after — concurrent retry double-charges
  result
end
```
