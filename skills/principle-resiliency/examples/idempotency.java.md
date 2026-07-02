# Resiliency — Java — Idempotency Key Dedup Store

## Problem

A payment `POST /charges` is non-idempotent. On network timeout the client retries, but
the server may have already processed the first request. An idempotency-key dedup store
prevents the second execution: reserve the key *before* the side effect, store the result
on completion, and return the stored result on any duplicate.

## Implementation

```java
// file: IdempotencyStore.java
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;

public class IdempotencyStore<T> {
    private enum Status { PENDING, COMPLETED }

    private record Entry<T>(Status status, T result) {}

    private final ConcurrentHashMap<String, Entry<T>> store = new ConcurrentHashMap<>();

    public T execute(String key, Supplier<T> operation) {
        // Reserve BEFORE executing — concurrent retry sees PENDING and stops.
        Entry<T> reserved = new Entry<>(Status.PENDING, null);
        Entry<T> existing = store.putIfAbsent(key, reserved);

        if (existing != null) {
            if (existing.status() == Status.COMPLETED) return existing.result();
            throw new IllegalStateException("key '" + key + "' already in-flight");
        }

        T result;
        try {
            result = operation.get();
        } catch (RuntimeException e) {
            store.remove(key);  // release — allows retry with same key
            throw e;
        }
        store.put(key, new Entry<>(Status.COMPLETED, result));
        return result;
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        var store = new IdempotencyStore<java.util.Map<String, Object>>();
        var calls = new int[]{0};

        java.util.function.Supplier<java.util.Map<String, Object>> charge = () -> {
            calls[0]++;
            return java.util.Map.of("charge_id", "ch_123", "amount", 100);
        };

        String key = "order-abc-attempt-1";
        var r1 = store.execute(key, charge);
        var r2 = store.execute(key, charge); // duplicate — returns cached result

        assert r1.equals(r2);
        assert calls[0] == 1 : "charge executed " + calls[0] + " times — expected 1";
        System.out.println("charge_id=" + r1.get("charge_id") + " calls=" + calls[0]);
    }
}
```

## Common Mistake

Recording the key *after* the side effect leaves a race window where a concurrent retry
sees no record and executes again.

```java
public T executeUnsafe(String key, Supplier<T> op) {
    T result = op.get();          // ✗ side effect runs first
    store.put(key, result);       // ✗ key recorded after — concurrent retry double-charges
    return result;
}
```
