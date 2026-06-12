# Error Handling — Ruby — HTTP Fetch with Retry

## Problem

Ruby's exception hierarchy lets you rescue the narrowest class first, so transient
failures are retried while permanent ones bubble immediately. Injecting an abstract
`Transport` base keeps the retry logic testable with a fake that returns a canned
sequence, and `rand(0.5..1.5)` jitter prevents thundering-herd backoff collisions.

## Implementation

```ruby
# file: transport.rb
Response = Struct.new(:status, :body)

class FetchError < StandardError; end
class TransientError < FetchError
  attr_reader :status
  def initialize(status) = (@status = status; super("transient #{status}"))
end
class PermanentError < FetchError
  attr_reader :status
  def initialize(status) = (@status = status; super("permanent #{status}"))
end
class TimeoutError  < FetchError; end
class ExhaustedError < FetchError; end

class Transport
  def fetch(url) = raise NotImplementedError
end

class FakeTransport < Transport
  def initialize = (@attempt = 0)

  def fetch(url)
    raise PermanentError.new(404) if url == "/not-found"
    attempt = @attempt
    @attempt += 1
    raise TimeoutError, "simulated timeout" if attempt < 2
    Response.new(200, "OK")
  end
end
```

```ruby
# file: fetch.rb
require_relative "transport"

# Retries transient failures with exponential backoff + jitter.
# timeout_ms is a parameter modelled in FakeTransport; real impl uses Net::HTTP#open_timeout.
def fetch_with_retry(transport, url, max_retries: 5, timeout_ms: 1000)
  base_ms = 100
  max_retries.times do |attempt|
    return transport.fetch(url)
  rescue PermanentError
    raise                          # bubble immediately — never retry
  rescue TransientError, TimeoutError
    delay = base_ms * (2**attempt) * rand(0.5..1.5)
    # sleep(delay / 1000.0) — real impl uses Kernel#sleep
    _ = delay
  rescue FetchError
    raise
  end
  raise ExhaustedError, "exhausted #{max_retries} retries on #{url}"
end
```

```ruby
# file: main.rb
require_relative "transport"
require_relative "fetch"

t = FakeTransport.new

# transient → success (attempts 0,1 raise TimeoutError; attempt 2 returns 200)
begin
  resp = fetch_with_retry(t, "/api/data")
  puts "status=#{resp.status} body=#{resp.body}"
rescue ExhaustedError => e
  puts "exhausted: #{e.message}"
end

# permanent → fail immediately
t2 = FakeTransport.new
begin
  fetch_with_retry(t2, "/not-found")
rescue PermanentError => e
  puts "permanent #{e.status} — no retries"
end
```

## Common Mistake

Rescuing all errors and retrying with no backoff and no permanent distinction retries
404s and auth failures indefinitely.

```ruby
max_retries.times do
  return transport.fetch(url)
rescue FetchError  # ✗ rescues PermanentError too — no classify
  # ✗ no backoff — tight loop until attempts exhausted
end
```
