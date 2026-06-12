# Caching — Ruby — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```ruby
# file: cache_aside.rb
require 'monitor'

# Cache-aside with per-key MonitorMixin for single-flight on cold/expired keys.
class CacheAside
  Entry = Struct.new(:value, :expires_at)

  def initialize(ttl:, &loader)
    @ttl = ttl
    @loader = loader
    @store = {}
    @locks = Hash.new { |h, k| h[k] = Monitor.new }
    @global = Monitor.new
  end

  def get(key)
    entry = @global.synchronize { @store[key] }
    return entry.value if entry && Time.now < entry.expires_at

    # Per-key Monitor: only one thread recomputes on a cold/expired hit.
    # @locks itself is a Hash — guard its access with @global to avoid two threads
    # creating different Monitor instances for the same key (breaking single-flight).
    lock = @global.synchronize { @locks[key] }
    lock.synchronize do
      entry = @global.synchronize { @store[key] }
      return entry.value if entry && Time.now < entry.expires_at

      value = @loader.call(key)
      @global.synchronize { @store[key] = Entry.new(value, Time.now + @ttl) }
      value
    end
  end
end
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```ruby
# ✗ no per-key lock — multiple threads call @loader concurrently on a cold key
entry = @store[key]
return entry.value if entry && Time.now < entry.expires_at
value = @loader.call(key) # ✗ thundering herd: all threads miss and hit the origin
@store[key] = Entry.new(value, Time.now + @ttl)
value
```
