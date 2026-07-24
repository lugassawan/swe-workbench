# Decorator — C# — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior without modifying `HttpFetcher`.
The `IFetcher` interface lets `RetryFetcher` and `LoggingFetcher` each hold an inner
`IFetcher`, add one concern, and delegate the rest. They compose in any order — the
core class stays untouched.

## Implementation

```csharp
// file: IFetcher.cs
public interface IFetcher
{
    string Fetch(string url);
}
```

```csharp
// file: HttpFetcher.cs
using System.Net.Http;

public sealed class HttpFetcher : IFetcher
{
    private static readonly HttpClient _client = new();

    public string Fetch(string url) =>
        _client.GetStringAsync(url).GetAwaiter().GetResult();
}
```

```csharp
// file: RetryFetcher.cs
public sealed class RetryFetcher : IFetcher
{
    private readonly IFetcher _inner;
    private readonly int _retries;

    public RetryFetcher(IFetcher inner, int retries)
    {
        _inner = inner;
        _retries = retries;
    }

    public string Fetch(string url)
    {
        Exception? last = null;
        for (int i = 0; i <= _retries; i++)
        {
            try { return _inner.Fetch(url); }
            catch (Exception ex) { last = ex; }
        }
        throw last!;
    }
}
```

```csharp
// file: LoggingFetcher.cs
public sealed class LoggingFetcher : IFetcher
{
    private readonly IFetcher _inner;

    public LoggingFetcher(IFetcher inner) => _inner = inner;

    public string Fetch(string url)
    {
        Console.WriteLine($"[fetch] GET {url}");
        try
        {
            var result = _inner.Fetch(url);
            Console.WriteLine($"[fetch] OK  {url}");
            return result;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[fetch] ERR {url}: {ex.Message}");
            throw;
        }
    }
}
```

```csharp
// file: Program.cs
IFetcher fetcher = new LoggingFetcher(new RetryFetcher(new HttpFetcher(), 3));
Console.WriteLine(fetcher.Fetch("https://example.com/api/data"));
```

## Common Mistake

Subclassing `HttpFetcher` with a combined class — behaviors cannot be reused
independently and every new combination requires its own subclass.

```csharp
// ✗ subclass explosion — retry + logging locked into one class
class RetryLoggingFetcher : HttpFetcher           // ✗ fused behaviors
{
    public override string Fetch(string url)
    {
        Console.WriteLine($"[fetch] GET {url}");  // ✗ cannot retry without logging
        for (int i = 0; i < 3; i++)
            try { return base.Fetch(url); } catch { }
        throw new Exception("all retries failed");
    }
}
// class CachingRetryFetcher : HttpFetcher { ... } // ✗ N behaviors → N² subclasses
```
