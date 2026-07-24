# Decorator — Java — Retry and Logging Fetch

## Problem

A core HTTP fetch needs retry and logging behavior added without altering the
`HttpFetcher` class. The classic GoF Decorator wraps a `Fetcher` interface:
`RetryFetcher` and `LoggingFetcher` each hold an inner `Fetcher` and delegate to it,
adding their own behavior before or after. They compose in any order and the core
class is never touched.

## Implementation

```java
// file: Fetcher.java
public interface Fetcher {
    String fetch(String url) throws Exception;
}
```

```java
// file: HttpFetcher.java
import java.net.URI;
import java.net.http.*;

public class HttpFetcher implements Fetcher {
    private static final HttpClient CLIENT = HttpClient.newHttpClient();

    @Override
    public String fetch(String url) throws Exception {
        var req = HttpRequest.newBuilder(URI.create(url)).GET().build();
        return CLIENT.send(req, HttpResponse.BodyHandlers.ofString()).body();
    }
}
```

```java
// file: RetryFetcher.java
public class RetryFetcher implements Fetcher {
    private final Fetcher inner;
    private final int retries;

    public RetryFetcher(Fetcher inner, int retries) {
        this.inner = inner;
        this.retries = retries;
    }

    @Override
    public String fetch(String url) throws Exception {
        Exception last = null;
        for (int i = 0; i <= retries; i++) {
            try { return inner.fetch(url); }
            catch (Exception e) { last = e; }
        }
        throw last;
    }
}
```

```java
// file: LoggingFetcher.java
public class LoggingFetcher implements Fetcher {
    private final Fetcher inner;

    public LoggingFetcher(Fetcher inner) { this.inner = inner; }

    @Override
    public String fetch(String url) throws Exception {
        System.out.println("[fetch] GET " + url);
        try {
            String result = inner.fetch(url);
            System.out.println("[fetch] OK  " + url);
            return result;
        } catch (Exception e) {
            System.out.println("[fetch] ERR " + url + ": " + e.getMessage());
            throw e;
        }
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) throws Exception {
        Fetcher fetcher = new LoggingFetcher(new RetryFetcher(new HttpFetcher(), 3));
        System.out.println(fetcher.fetch("https://example.com/api/data"));
    }
}
```

## Common Mistake

Extending `HttpFetcher` with a combined subclass — every new behavior combination
requires a new class, and the behaviors cannot be reused independently.

```java
// ✗ subclass explosion — every combination needs its own class
class RetryLoggingFetcher extends HttpFetcher {  // ✗ fuses retry + logging
    @Override
    public String fetch(String url) throws Exception {
        System.out.println("[fetch] GET " + url);  // ✗ cannot retry without logging
        for (int i = 0; i < 3; i++) {
            try { return super.fetch(url); }
            catch (Exception e) { /* retry */ }
        }
        throw new Exception("all retries failed");
    }
}
// class CachingRetryFetcher extends HttpFetcher { ... }  // ✗ N behaviors → N² classes
```
