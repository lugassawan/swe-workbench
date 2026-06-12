# Decorator — Ruby — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior without modifying `http_fetch`
itself. Ruby's proc composition makes the Decorator pattern idiomatic: `with_retry`
and `with_logging` each wrap a callable and return a new one. They compose in any
order using `>>` or explicit lambdas, keeping each behavior independently reusable.

## Implementation

```ruby
# file: fetcher.rb
require "net/http"
require "uri"

module Fetcher
  HTTP_FETCH = lambda do |url|
    uri = URI.parse(url)
    Net::HTTP.get_response(uri).body
  end

  def self.with_retry(fn, n)
    lambda do |url|
      last_err = nil
      (n + 1).times do
        begin
          return fn.call(url)
        rescue => e
          last_err = e
        end
      end
      raise last_err
    end
  end

  def self.with_logging(fn)
    lambda do |url|
      puts "[fetch] GET #{url}"
      begin
        result = fn.call(url)
        puts "[fetch] OK  #{url}"
        result
      rescue => e
        puts "[fetch] ERR #{url}: #{e.message}"
        raise
      end
    end
  end
end
```

```ruby
# file: main.rb
require_relative "fetcher"

fetch = Fetcher.with_logging(Fetcher.with_retry(Fetcher::HTTP_FETCH, 3))
puts fetch.call("https://example.com/api/data")
# [fetch] GET https://example.com/api/data
# [fetch] OK  https://example.com/api/data
```

## Common Mistake

Combining retry and logging into a single method — the behaviors are inseparable and
every new combination requires a new method.

```ruby
# ✗ subclass explosion — retry and logging merged; behaviors cannot be reused alone
def retry_logging_fetch(url, retries: 3)     # ✗ fused behaviors
  puts "[fetch] GET #{url}"                   # ✗ cannot retry without logging
  retries.times do
    begin
      return http_get(url)
    rescue => _e
      nil
    end
  end
  raise "all retries failed"
  # ✗ adding caching needs retry_logging_caching_fetch, caching_fetch, …
end
```
