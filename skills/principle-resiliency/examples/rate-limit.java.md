# Resiliency — Java — Token-Bucket Rate Limiter

## Problem

A client hammering an API with synchronized retries causes a thundering herd. A token-bucket
limiter controls burst capacity and enforces a steady refill rate. When the bucket is empty
the caller backs off with random jitter instead of retrying at a fixed cadence.

## Implementation

```java
// file: TokenBucket.java
import java.util.concurrent.locks.ReentrantLock;

public class TokenBucket {
    private final double capacity;
    private final double refillPerMs;
    private double tokens;
    private long lastRefillMs;
    private final ReentrantLock lock = new ReentrantLock();

    public TokenBucket(double capacity, double refillPerSecond) {
        this.capacity = capacity;
        this.refillPerMs = refillPerSecond / 1000.0;
        this.tokens = capacity;
        this.lastRefillMs = System.currentTimeMillis();
    }

    public boolean tryAcquire() {
        lock.lock();
        try {
            long now = System.currentTimeMillis();
            double elapsed = now - lastRefillMs;
            tokens = Math.min(capacity, tokens + elapsed * refillPerMs);
            lastRefillMs = now;
            if (tokens >= 1) { tokens--; return true; }
            return false;
        } finally {
            lock.unlock();
        }
    }
}
```

```java
// file: RateLimitedCaller.java
import java.util.Random;
import java.util.concurrent.Callable;

public class RateLimitedCaller {
    private static final Random RNG = new Random();

    public static <T> T call(TokenBucket bucket, Callable<T> op, int maxAttempts) throws Exception {
        for (int attempt = 0; attempt < maxAttempts; attempt++) {
            if (bucket.tryAcquire()) return op.call();
            // Jitter prevents synchronized retries (thundering herd).
            long backoff = (long) ((1 << attempt) * (0.5 + RNG.nextDouble()));
            Thread.sleep(backoff);
        }
        throw new RuntimeException("rate limit exhausted");
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) throws Exception {
        var bucket = new TokenBucket(3, 1.0); // 3-token burst, 1/sec refill
        for (int i = 0; i < 5; i++) {
            final int idx = i;
            try {
                String result = RateLimitedCaller.call(bucket, () -> "ok-" + idx, 5);
                System.out.println(result);
            } catch (RuntimeException e) {
                System.out.println("rejected");
            }
        }
    }
}
```

## Common Mistake

A fixed-window counter allows up to 2× the limit at window boundaries.

```java
class FixedWindowUnsafe {
    private int count = 0;
    private long windowStart = System.currentTimeMillis();

    public boolean tryAcquire() {
        long now = System.currentTimeMillis();
        if (now - windowStart >= windowMs) {
            count = 0;             // ✗ hard reset enables boundary burst
            windowStart = now;
        }
        if (count < limit) { count++; return true; }
        return false;
    }
    FixedWindowUnsafe(int limit, long windowMs) { this.limit = limit; this.windowMs = windowMs; }
    private final int limit; private final long windowMs;
}
```
