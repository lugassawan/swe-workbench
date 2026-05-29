---
name: language-csharp
description: C# and .NET idioms — .NET 8 LTS, csproj, C# NRT, records, value semantics, switch expressions, async/await, Task, ValueTask, CancellationToken, ConfigureAwait, dependency injection, IOptions<T>, LINQ, and performance. Auto-load when working with .cs files, .csproj, .sln, Directory.Build.props, or when the user mentions C#, dotnet, .NET 8, C# NRT, NRT, records, value semantics, switch expressions, Task, ValueTask, CancellationToken, ConfigureAwait, IOptions, or LINQ.
---

# C# / .NET

## .NET 8 project shape
- Prefer SDK-style projects with explicit `TargetFramework` (`net8.0`) and shared defaults in `Directory.Build.props`.
- Keep nullable reference types enabled for new code: `<Nullable>enable</Nullable>`.
- Use `ImplicitUsings` when the repository already does; avoid hand-maintaining noisy common imports.
- Keep application, domain, infrastructure, and test projects separate when boundaries are real, not just for ceremony.

```xml
<PropertyGroup>
  <TargetFramework>net8.0</TargetFramework>
  <Nullable>enable</Nullable>
  <ImplicitUsings>enable</ImplicitUsings>
</PropertyGroup>
```

## Nullable reference types
- Treat warnings as design feedback, not noise. Model absence with `T?`, `required`, or a domain type.
- Validate nullable inputs at boundaries; keep internals non-null where possible.
- Use `ArgumentNullException.ThrowIfNull(value)` for guard clauses.
- Avoid `!` except when bridging a framework or serializer limitation; leave a short reason.

```csharp
public sealed class User
{
    public required string Email { get; init; }
    public string? DisplayName { get; init; }
}
```

## Records and value semantics
- Use `record` or `readonly record struct` for immutable value-like data.
- Use classes for identity, lifecycle, mutation, or behavior-heavy objects.
- Be deliberate with `with`: it is copy-with-change, not validation unless constructors enforce invariants.

```csharp
public sealed record Money(decimal Amount, string Currency);

var discounted = price with { Amount = price.Amount * 0.9m };
```

## Pattern matching
- Use patterns for shape-based branching, parsing, and closed domain states.
- Prefer switch expressions when every case returns a value.
- Keep guards (`when`) simple; complex decisions deserve named methods.

```csharp
return command switch
{
    CreateUser(var email) when email.Contains('@') => Create(email),
    DeleteUser(var id) => Delete(id),
    _ => throw new InvalidOperationException("unsupported command")
};
```

## Async and cancellation
- Use `async`/`await` all the way. Avoid `.Result`, `.Wait()`, and blocking over async work.
- Accept and pass `CancellationToken` through I/O, database, and long-running operations.
- In libraries, use `ConfigureAwait(false)` when code does not need a captured context; in modern app code, follow the repo's convention.
- Prefer `Task.WhenAll` for independent work; avoid unobserved fire-and-forget tasks.

```csharp
public async Task<User> GetUserAsync(string id, CancellationToken cancellationToken)
{
    ArgumentException.ThrowIfNullOrWhiteSpace(id);
    return await repository.FindAsync(id, cancellationToken).ConfigureAwait(false)
        ?? throw new UserNotFoundException(id);
}
```

## Dependency injection and options
- Depend on abstractions at boundaries, but do not create interfaces for every class by habit.
- Use constructor injection for required collaborators; avoid service locator patterns.
- Bind configuration to option records and consume `IOptions<T>`, `IOptionsSnapshot<T>`, or `IOptionsMonitor<T>` based on lifetime needs.
- Validate options at startup when invalid configuration should fail fast.

```csharp
public sealed record RetryOptions
{
    public int MaxAttempts { get; init; } = 3;
}

public sealed class Worker(IOptions<RetryOptions> options)
{
    private readonly RetryOptions retry = options.Value;
}
```

## LINQ and performance
- Use LINQ for clear transformations, filtering, grouping, and projections.
- Prefer `Any()` over `Count() > 0`, and avoid repeated enumeration of deferred queries.
- In hot paths, benchmark before replacing readable LINQ with loops.
- Use `Span<T>`, pooling, and allocation-aware APIs only when profiling shows they matter.

```csharp
var activeEmails = users
    .Where(user => user.IsActive)
    .Select(user => user.Email)
    .ToArray();
```

## Testing
- xUnit, NUnit, and MSTest are all fine; follow the repository's existing framework.
- Use fluent assertions when already present, and keep tests behavior-focused.
- Mock external boundaries, not records, value objects, or simple domain behavior.

## Avoid
- Disabling nullable warnings instead of fixing the contract.
- Blocking on tasks with `.Result`, `.Wait()`, or `GetAwaiter().GetResult()`.
- Treating dependency injection as a reason to hide every constructor behind an interface.
- Rewriting clear LINQ into loops without a measured performance reason.
- Making ASP.NET conventions the default for non-web .NET code.
