# Bounded Fan-out — Java — fixed thread pool with invokeAll

## Problem

Fetch N items concurrently on a fixed thread pool of K=5 threads using `invokeAll`.
The executor enforces the concurrency cap structurally — threads block in the pool queue
rather than starting without limit. `invokeAll` blocks until every `Callable` completes
and returns `List<Future<String>>` in the same order as submission, so results are
already ordered without extra sorting.

## Implementation

```java
// file: bounded-fan-out.java
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;

public class BoundedFanOut {

    static String fetch(String id) throws InterruptedException {
        Thread.sleep(10);
        return "result-" + id;
    }

    public static void main(String[] args) throws Exception {
        List<String> ids = List.of("a", "b", "c", "d", "e", "f", "g", "h");
        final int K = 5;

        ExecutorService executor = Executors.newFixedThreadPool(K);
        try {
            List<Callable<String>> tasks = new ArrayList<>();
            for (String id : ids) {
                tasks.add(() -> fetch(id));
            }

            // invokeAll blocks until all tasks finish; order matches submission.
            List<Future<String>> futures = executor.invokeAll(tasks);

            List<String> results = new ArrayList<>();
            for (Future<String> f : futures) {
                results.add(f.get()); // already in original order
            }
            System.out.println(results);
        } finally {
            executor.shutdown();
        }
    }
}
```

## Common Mistake

`newCachedThreadPool` spins up one thread per task with no cap.

```java
// ✗ cached pool creates an unbounded number of threads
ExecutorService badExecutor = Executors.newCachedThreadPool();
List<CompletableFuture<String>> futures = ids.stream()
    .map(id -> CompletableFuture.supplyAsync(() -> fetch(id), badExecutor)) // ✗ all at once
    .toList();
CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join(); // ✗ no limit
```
