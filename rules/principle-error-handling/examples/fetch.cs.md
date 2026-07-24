# Error Handling — C# — HTTP Fetch with Retry

## Problem

C# exceptions carry rich metadata, so a `FetchException` with an `IsTransient` property
lets the retry loop classify errors without a parallel enum. Injecting an `ITransport`
interface keeps the retry logic testable with a deterministic fake, and
`Random.Shared.NextDouble()` provides jitter without allocating a new `Random` instance.

## Implementation

```csharp
// file: Transport.cs
public record Response(int Status, string Body);

public class FetchException : Exception
{
    public bool IsTransient { get; }
    public int? StatusCode  { get; }
    public FetchException(string message, bool isTransient, int? statusCode = null)
        : base(message) { IsTransient = isTransient; StatusCode = statusCode; }
}

public class ExhaustedFetchException : FetchException
{
    public ExhaustedFetchException(int attempts)
        : base($"Exhausted {attempts} retries", isTransient: false) { }
}

public interface ITransport
{
    Response Fetch(string url);
}

public class FakeTransport : ITransport
{
    private int _attempt;

    public Response Fetch(string url)
    {
        if (url == "/not-found")
            throw new FetchException("404 Not Found", isTransient: false, statusCode: 404);
        int a = _attempt++;
        if (a < 2) throw new FetchException("Timeout", isTransient: true);
        return new Response(200, "OK");
    }
}
```

```csharp
// file: FetchWithRetry.cs
public static class FetchWithRetry
{
    private const int BaseMs = 100;

    // Retries transient failures with exponential backoff + jitter.
    // timeoutMs modelled in FakeTransport; real impl: await Task.Delay(delay, cancellationToken)
    public static Response Fetch(
        ITransport transport, string url, int maxRetries, int timeoutMs)
    {
        for (int attempt = 0; attempt < maxRetries; attempt++)
        {
            try
            {
                return transport.Fetch(url);
            }
            catch (FetchException ex) when (!ex.IsTransient)
            {
                throw;    // permanent — bubble immediately
            }
            catch (FetchException)
            {
                double delay = BaseMs * Math.Pow(2, attempt)
                             * (Random.Shared.NextDouble() + 0.5);
                _ = delay; // await Task.Delay((int)delay) — real impl
            }
        }
        throw new ExhaustedFetchException(maxRetries);
    }
}
```

```csharp
// file: Program.cs
var t = new FakeTransport();

// transient → success (attempts 0,1 throw Timeout; attempt 2 returns 200)
try
{
    var r = FetchWithRetry.Fetch(t, "/api/data", maxRetries: 5, timeoutMs: 1000);
    Console.WriteLine($"status={r.Status} body={r.Body}");
}
catch (ExhaustedFetchException e) { Console.WriteLine($"exhausted: {e.Message}"); }

// permanent → fail immediately
var t2 = new FakeTransport();
try
{
    FetchWithRetry.Fetch(t2, "/not-found", maxRetries: 5, timeoutMs: 1000);
}
catch (FetchException e)
{
    Console.WriteLine($"permanent {e.StatusCode} transient={e.IsTransient}");
}
```

## Common Mistake

Catching all exceptions and retrying with no backoff wastes the retry budget on
unrecoverable 404s and auth failures.

```csharp
while (attempts < maxRetries) {
    try { return transport.Fetch(url); }
    catch (FetchException) {  // ✗ catches permanent errors — no IsTransient check
        attempts++;            // ✗ no backoff — tight loop
    }
}
```
