# Bounded Fan-out — Ruby — thread pool consuming a Queue

## Problem

Fetch N items concurrently in Ruby using K=5 worker threads that drain a shared `Queue`.
Pre-enqueue `[i, id]` pairs so each worker captures the original index alongside the item.
Sentinel `nil` values (one per worker) signal shutdown. Workers write `results[i] = fetch(id)`
to their owned index slot — no mutex needed — then `workers.each(&:join)` collects them all.

## Implementation

```ruby
# file: bounded-fan-out.rb
def fetch(id)
  sleep(0.01)
  "result-#{id}"
end

ids     = %w[a b c d e f g h]
K       = 5
results = Array.new(ids.size)
queue   = Queue.new

ids.each_with_index { |id, i| queue.push([i, id]) }
K.times { queue.push(nil) } # one sentinel per worker

workers = K.times.map do
  Thread.new do
    loop do
      item = queue.pop
      break if item.nil?       # sentinel: this worker is done
      i, id = item
      results[i] = fetch(id)   # write to owned index slot
    end
  end
end

workers.each(&:join)
puts results.inspect
```

## Common Mistake

Creating one thread per item with `Thread.new` inside `map` is unbounded.

```ruby
# ✗ one thread per item — no pool, no cap
bad_results = ids.map { |id| Thread.new { fetch(id) } }.map(&:value) # ✗ unbounded threads
```
