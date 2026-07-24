# Error Handling — Java — HTTP Fetch with Retry

## Problem

Java checked exceptions make the failure contract visible in method signatures, but
the retry loop needs to distinguish transient from permanent failures before deciding
whether to catch-and-continue or rethrow. Injecting a `Transport` interface decouples
the retry policy from real HTTP and keeps the fake implementation self-contained.

## Implementation

```java
// file: Transport.java
public record Response(int status, String body) {}

public class FetchException extends Exception {
    private final boolean transient_;
    public FetchException(String msg, boolean transient_) {
        super(msg);
        this.transient_ = transient_;
    }
    public boolean isTransient() { return transient_; }
}

public interface Transport {
    Response fetch(String url) throws FetchException;
}

public class FakeTransport implements Transport {
    private int attempt = 0;

    @Override
    public Response fetch(String url) throws FetchException {
        if ("/not-found".equals(url)) {
            throw new FetchException("404 Not Found", false); // permanent
        }
        int a = attempt++;
        if (a < 2) throw new FetchException("timeout", true); // transient
        return new Response(200, "OK");
    }
}
```

```java
// file: FetchWithRetry.java
public class FetchWithRetry {
    private static final int BASE_MS = 100;

    /**
     * Retries transient failures with exponential backoff + jitter.
     * timeoutMs is a parameter modelled in FakeTransport; real impl uses
     * HttpClient.newBuilder().connectTimeout(Duration.ofMillis(timeoutMs)).
     */
    public static Response fetch(
            Transport transport, String url, int maxRetries, int timeoutMs)
            throws FetchException {
        FetchException last = null;
        for (int attempt = 0; attempt < maxRetries; attempt++) {
            try {
                return transport.fetch(url);
            } catch (FetchException e) {
                if (!e.isTransient()) throw e;   // permanent — bubble immediately
                last = e;
                double delay = BASE_MS * Math.pow(2, attempt) * (Math.random() + 0.5);
                // Thread.sleep((long) delay); — real impl uses Thread.sleep
            }
        }
        throw new FetchException("exhausted " + maxRetries + " retries on " + url, false);
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        FakeTransport t = new FakeTransport();

        // transient → success (attempts 0,1 throw timeout; attempt 2 returns 200)
        try {
            Response r = FetchWithRetry.fetch(t, "/api/data", 5, 1000);
            System.out.println("status=" + r.status() + " body=" + r.body());
        } catch (FetchException e) {
            System.out.println("exhausted: " + e.getMessage());
        }

        // permanent → fail immediately
        FakeTransport t2 = new FakeTransport();
        try {
            FetchWithRetry.fetch(t2, "/not-found", 5, 1000);
        } catch (FetchException e) {
            System.out.println("permanent: " + e.getMessage() + " transient=" + e.isTransient());
        }
    }
}
```

## Common Mistake

Catching every exception and continuing in a tight loop retries auth failures and 404s
with no backoff, burning the retry budget on unrecoverable errors.

```java
for (int i = 0; i < maxRetries; i++) {
    try {
        return transport.fetch(url);
    } catch (FetchException e) { // ✗ catches permanent errors too — no classify
        continue;                 // ✗ no backoff — tight loop
    }
}
```
