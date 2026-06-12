# Error Handling — Ruby — Config Parse & Validate

## Problem

Ruby's exception system is expressive but easy to misuse by rescuing `StandardError`
too broadly. A hierarchy rooted at `ConfigError < StandardError` with subclasses for
each tier lets callers rescue exactly what they can handle, while structured `rescue`
blocks re-raise wrapped errors so the original cause is never silently dropped.

## Implementation

```ruby
# file: config.rb

class ConfigError < StandardError; end

class IoConfigError < ConfigError; end

class ParseConfigError < ConfigError
  attr_reader :line
  def initialize(line, reason)
    super("line #{line}: #{reason}")
    @line = line
  end
end

class ValidationConfigError < ConfigError
  attr_reader :field
  def initialize(field, reason)
    super("field '#{field}': #{reason}")
    @field = field
  end
end

def parse_config(path)
  begin
    lines = File.readlines(path, encoding: "utf-8")
  rescue SystemCallError => e
    raise IoConfigError, "cannot read '#{path}': #{e.message}"
  end

  kv = {}
  lines.each_with_index do |raw, idx|
    line = raw.strip
    next if line.empty? || line.start_with?("#")
    unless line.include?("=")
      raise ParseConfigError.new(idx + 1, "missing '=' separator")
    end
    key, value = line.split("=", 2).map(&:strip)
    raise ParseConfigError.new(idx + 1, "empty key") if key.nil? || key.empty?
    kv[key] = value
  end

  validate_config(kv)
end

def validate_config(kv)
  %w[host port].each do |field|
    raise ValidationConfigError.new(field, "required key missing") unless kv.key?(field)
  end
  begin
    port = Integer(kv["port"])
  rescue ArgumentError
    raise ValidationConfigError.new("port", "'#{kv['port']}' is not an integer")
  end
  raise ValidationConfigError.new("port", "#{port} out of range 1-65535") unless (1..65535).cover?(port)
  kv
end
```

```ruby
# file: main.rb
require_relative "config"

begin
  cfg = parse_config("app.conf")
  puts "host=#{cfg['host']} port=#{cfg['port']}"
rescue IoConfigError => e
  warn "IO error: #{e.message}"
rescue ParseConfigError => e
  warn "Parse error at line #{e.line}: #{e.message}"
rescue ValidationConfigError => e
  warn "Validation error for '#{e.field}': #{e.message}"
end
```

## Common Mistake

Rescuing all errors and returning an empty hash — the caller sees valid-looking data with no indication that anything failed.

```ruby
def parse_config(path)
  # ... parsing ...
rescue => _e        # ✗ catches every tier
  return {}         # ✗ caller gets empty hash; no error propagates
end
```
