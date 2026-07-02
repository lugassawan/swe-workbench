---
name: language-ruby
description: Ruby idioms — Ruby 3.x pattern matching, blocks, procs, lambdas, Enumerable, Comparable, frozen string literals, error handling, and testing. Auto-load when working with .rb files, Gemfile, Rakefile, gemspecs, or when the user mentions Ruby, Bundler, RSpec, minitest, blocks, procs, lambdas, or pattern matching.
---

# Ruby

## Ruby 3.x syntax
- Use pattern matching for structural dispatch on hashes, arrays, and domain data; avoid using it as a verbose `if/elsif`.
- Prefer endless methods only for tiny, obvious expressions. Multi-step behavior deserves a normal `def`.
- Hash shorthand (`{name:, email:}`) is clear when local names match keys; use explicit pairs when transformation happens.
- Use Ractor for isolated parallelism only when its object-sharing constraints fit better than threads or processes.

```ruby
case payload
in {type: "user_created", id:, email:}
  create_user(id:, email:)
in {type: "user_deleted", id:}
  delete_user(id)
else
  raise ArgumentError, "unknown payload"
end

def active? = status == "active"
```

## Blocks, procs, and lambdas
- Blocks are the default for one-off callbacks and iteration; yield when the method owns the flow.
- `Proc` is lenient about arity and `return`; use it for flexible callbacks only when that behavior is intentional.
- Lambdas behave like methods for arity and return locally. Prefer them for stored callable behavior.

```ruby
def with_lock(lock)
  lock.acquire
  yield
ensure
  lock.release
end

normalize = ->(value) { value.to_s.strip.downcase }
```

## Frozen string literals
- Add `# frozen_string_literal: true` to new files unless the project has a different convention.
- Treat strings as immutable values; use `String.new`, unary `+`, or `dup` when mutation is required.
- Avoid hidden mutation of arguments. Return a new string unless the method name clearly signals mutation with `!`.

## Enumerable and Comparable
- Include `Enumerable` when the type can define a meaningful `each`.
- Include `Comparable` when `<=>` has a total ordering that callers will agree with.
- Prefer `map`, `filter`, `each_with_object`, `tally`, and `sum` over manual accumulator loops.

```ruby
class Money
  include Comparable
  attr_reader :cents

  def initialize(cents) = @cents = cents
  def <=>(other) = cents <=> other.cents
end
```

## Error handling
- Rescue the narrowest exception class you can actually handle.
- Keep `begin`/`rescue` scopes small so unrelated failures are not swallowed.
- Avoid bare `rescue` (no class specified); the implicit `StandardError` scope hides intent and can silently swallow subclasses you did not anticipate. Always name the class explicitly.
- Re-raise with context when crossing a boundary; preserve the original exception when useful.

```ruby
def load_config(path)
  JSON.parse(File.read(path), symbolize_names: true)
rescue Errno::ENOENT => e
  raise ConfigMissing, "missing config at #{path}: #{e.message}"
end
```

## Framework-neutral conventions
- Plain Ruby objects are enough for domain behavior; do not require Rails, ActiveSupport, or callbacks unless the project already uses them.
- Keep files, constants, and namespaces aligned so autoloaders and simple `require` calls both stay predictable.
- Use Bundler for dependency boundaries, Rake for project tasks, and gemspecs only when shipping a library.
- Rails-adjacent names like service objects, jobs, serializers, and presenters should describe ordinary Ruby objects first.

## Tooling
- **Format:** `rubocop -a` (safe autocorrect; no dedicated import tool in Ruby)
- **Lint:** `rubocop`
- **Test:** `rspec` / `rake test` (see Testing below)

## Testing
- RSpec favors expressive examples, matchers, and shared context; keep examples behavior-focused and avoid over-nesting.
- Minitest favors small stdlib tests with direct assertions; use it when simplicity and low dependency weight matter.
- Follow the repository's existing test style before introducing a second framework.

## Avoid
- Monkey-patching core classes outside a tightly controlled compatibility boundary.
- Clever metaprogramming when a method, module, or explicit object would be clearer.
- Mutating arguments without a clear `!` method name or documented contract.
- Broad `rescue StandardError` around large methods.
- Treating Rails conventions as Ruby requirements in non-Rails code.
