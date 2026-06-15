# Resiliency — C# — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```csharp
// file: TokenBucket.cs
using System;
using System.Threading;

public class TokenBucket
{
    private readonly double _capacity;
    private readonly double _refillPerMs;
    private double _tokens;
    private long _lastRefillMs;
    private readonly object _lock = new();

    public TokenBucket(double capacity, double refillPerSecond)
    {
        _capacity = capacity;
        _refillPerMs = refillPerSecond / 1000.0;
        _tokens = capacity;
        _lastRefillMs = Environment.TickCount64;
    }

    public bool TryAcquire()
    {
        lock (_lock)
        {
            long now = Environment.TickCount64;
            double elapsed = now - _lastRefillMs;
            _tokens = Math.Min(_capacity, _tokens + elapsed * _refillPerMs);
            _lastRefillMs = now;
            if (_tokens >= 1) { _tokens--; return true; }
            return false;
        }
    }
}
```

```csharp
// file: Program.cs
using System;
using System.Threading;
using System.Threading.Tasks;

var bucket = new TokenBucket(capacity: 3, refillPerSecond: 1.0);
var rng = new Random();

async Task<string> CallWithRateLimit(Func<string> op, int maxAttempts = 5)
{
    for (int attempt = 0; attempt < maxAttempts; attempt++)
    {
        if (bucket.TryAcquire()) return op();
        // Jitter prevents synchronized retries (thundering herd).
        int backoff = Math.Max(1, (int)((1 << attempt) * (0.5 + rng.NextDouble())));
        await Task.Delay(backoff);
    }
    throw new InvalidOperationException("rate limit exhausted");
}

for (int i = 0; i < 5; i++)
{
    int idx = i;
    try { Console.WriteLine(await CallWithRateLimit(() => $"ok-{idx}")); }
    catch { Console.WriteLine("rejected"); }
}
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```csharp
class FixedWindowUnsafe
{
    private int _count = 0;
    private long _windowStart = Environment.TickCount64;

    public bool TryAcquire()
    {
        long now = Environment.TickCount64;
        if (now - _windowStart >= _windowMs)
        {
            _count = 0;             // ✗ hard reset enables boundary burst
            _windowStart = now;
        }
        if (_count < _limit) { _count++; return true; }
        return false;
    }
    FixedWindowUnsafe(int limit, long windowMs) { _limit = limit; _windowMs = windowMs; }
    private readonly int _limit; private readonly long _windowMs;
}
```
