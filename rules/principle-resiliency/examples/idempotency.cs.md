# Resiliency — C# — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```csharp
// file: IdempotencyStore.cs
using System;
using System.Collections.Concurrent;

public class IdempotencyStore<T>
{
    private enum Status { Pending, Completed }
    private record Entry(Status Status, T? Result = default);

    private readonly ConcurrentDictionary<string, Entry> _store = new();

    public T Execute(string key, Func<T> operation)
    {
        // Reserve BEFORE executing — concurrent retry sees Pending and stops.
        var reserved = new Entry(Status.Pending);
        var existing = _store.GetOrAdd(key, reserved);

        if (!ReferenceEquals(existing, reserved))
        {
            if (existing.Status == Status.Completed) return existing.Result!;
            throw new InvalidOperationException($"key '{key}' already in-flight");
        }

        T result;
        try { result = operation(); }
        catch { _store.TryRemove(key, out _); throw; }  // release — allows retry
        _store[key] = new Entry(Status.Completed, result);
        return result;
    }
}
```

```csharp
// file: Program.cs
var store = new IdempotencyStore<Dictionary<string, object>>();
int calls = 0;

Dictionary<string, object> Charge()
{
    calls++;
    return new() { ["charge_id"] = "ch_123", ["amount"] = 100 };
}

const string key = "order-abc-attempt-1";
var r1 = store.Execute(key, Charge);
var r2 = store.Execute(key, Charge); // duplicate — returns cached result

Console.WriteLine(r1["charge_id"] == r2["charge_id"]); // True
Console.WriteLine($"calls={calls}");                   // calls=1
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```csharp
public T ExecuteUnsafe(string key, Func<T> op)
{
    var result = op();         // ✗ side effect runs first
    _store[key] = result;      // ✗ key recorded after — concurrent retry double-charges
    return result;
}
```
