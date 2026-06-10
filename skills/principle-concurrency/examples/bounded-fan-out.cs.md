# Bounded Fan-out — C# — SemaphoreSlim + Task.WhenAll

## Problem

Fetch N items concurrently in C# using `SemaphoreSlim` to cap inflight work at K=5.
Each task calls `await sem.WaitAsync()` before fetching and releases the semaphore in a
`finally` block to guarantee release on both success and exception. Pre-allocating
`results[i]` means each task writes to its own slot — no locking needed. `Task.WhenAll`
collects everything once all tasks complete, in original order.

## Implementation

```csharp
// file: bounded-fan-out.cs
using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

class BoundedFanOut
{
    static async Task<string> FetchAsync(string id)
    {
        await Task.Delay(10);
        return $"result-{id}";
    }

    static async Task Main()
    {
        var ids = new[] { "a", "b", "c", "d", "e", "f", "g", "h" };
        const int K = 5;
        var sem = new SemaphoreSlim(K);
        var results = new string[ids.Length];

        var tasks = ids.Select(async (id, i) =>
        {
            await sem.WaitAsync();
            try
            {
                results[i] = await FetchAsync(id); // each task owns its index slot
            }
            finally
            {
                sem.Release(); // always release, even on exception
            }
        });

        await Task.WhenAll(tasks);
        Console.WriteLine(string.Join(", ", results));
    }
}
```

## Common Mistake

`Task.WhenAll` over a direct projection launches all tasks at once with no cap.

```csharp
// ✗ all N tasks start immediately — no semaphore, no limit
static async Task BadFanOut(string[] ids) {
    await Task.WhenAll(ids.Select(FetchAsync)); // ✗ unbounded inflight
}
```
