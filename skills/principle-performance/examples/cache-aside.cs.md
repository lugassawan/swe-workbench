# Caching — C# — Cache-Aside with Single-Flight

## Problem

On a cache miss (or expired entry), concurrent callers for the same key will all hit the origin
simultaneously — the "thundering herd" or cache-stampede problem. The fix is single-flight: one
caller recomputes while all others wait and share the result. The cache stores the value with a TTL;
on a hit within the TTL, the value is returned immediately without touching the origin.

## Implementation

```csharp
// file: cache-aside.cs
using System.Collections.Concurrent;

// In-process cache entry: value + absolute expiry.
record CacheEntry<T>(T Value, DateTime ExpiresAt);

class CacheAside<T>
{
    private readonly ConcurrentDictionary<string, CacheEntry<T>> _store = new();
    // SemaphoreSlim per key — ensures only one caller recomputes on a cold/expired hit.
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _locks = new();
    private readonly TimeSpan _ttl;
    private readonly Func<string, Task<T>> _loader;

    public CacheAside(TimeSpan ttl, Func<string, Task<T>> loader)
    {
        _ttl = ttl;
        _loader = loader;
    }

    public async Task<T> GetAsync(string key)
    {
        if (_store.TryGetValue(key, out var entry) && entry.ExpiresAt > DateTime.UtcNow)
            return entry.Value;

        // Single-flight: acquire a per-key lock so only one caller recomputes.
        var sem = _locks.GetOrAdd(key, _ => new SemaphoreSlim(1, 1));
        await sem.WaitAsync();
        try
        {
            // Re-check after acquiring the lock — another caller may have already populated it.
            if (_store.TryGetValue(key, out entry) && entry.ExpiresAt > DateTime.UtcNow)
                return entry.Value;

            var value = await _loader(key);
            _store[key] = new CacheEntry<T>(value, DateTime.UtcNow.Add(_ttl));
            return value;
        }
        finally
        {
            sem.Release();
        }
    }
}
```

## Common Mistake

No single-flight guard: every concurrent miss for the same key calls the origin independently.

```csharp
// ✗ no lock — every concurrent miss calls _loader concurrently (thundering herd)
if (_store.TryGetValue(key, out var entry) && entry.ExpiresAt > DateTime.UtcNow)
    return entry.Value;
var value = await _loader(key); // ✗ N concurrent misses → N origin calls
_store[key] = new CacheEntry<T>(value, DateTime.UtcNow.Add(_ttl));
return value;
```
