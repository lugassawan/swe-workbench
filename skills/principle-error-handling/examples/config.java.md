# Error Handling — Java — Config Parse & Validate

## Problem

Java's checked exceptions force callers to acknowledge failure, but a single broad
`Exception` catch loses the distinction between an IO fault, a bad line, and a missing
key. Three `ConfigException` subclasses, each wrapping its cause via `super(msg, cause)`,
give callers precise `catch` branches while preserving the full stack trace.

## Implementation

```java
// file: ConfigLoader.java
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class ConfigLoader {

    public static class ConfigException extends Exception {
        public ConfigException(String msg) { super(msg); }
        public ConfigException(String msg, Throwable cause) { super(msg, cause); }
    }
    public static class IoConfigException extends ConfigException {
        public IoConfigException(String msg, Throwable cause) { super(msg, cause); }
    }
    public static class ParseConfigException extends ConfigException {
        public final int line;
        public ParseConfigException(int line, String reason) {
            super("line " + line + ": " + reason); this.line = line;
        }
    }
    public static class ValidationConfigException extends ConfigException {
        public final String field;
        public ValidationConfigException(String field, String reason) {
            super("field '" + field + "': " + reason); this.field = field;
        }
        public ValidationConfigException(String field, String reason, Throwable cause) {
            super("field '" + field + "': " + reason, cause); this.field = field;
        }
    }

    public record Config(String host, int port) {}

    public static Config parse(String path) throws ConfigException {
        List<String> lines;
        try {
            lines = Files.readAllLines(Path.of(path));
        } catch (IOException e) {
            throw new IoConfigException("cannot read '" + path + "'", e);
        }

        Map<String, String> kv = new LinkedHashMap<>();
        for (int n = 0; n < lines.size(); n++) {
            String line = lines.get(n).strip();
            if (line.isEmpty() || line.startsWith("#")) continue;
            int eq = line.indexOf('=');
            if (eq < 1) throw new ParseConfigException(n + 1, "missing '=' separator");
            String key = line.substring(0, eq).strip();
            if (key.isEmpty()) throw new ParseConfigException(n + 1, "empty key");
            kv.put(key, line.substring(eq + 1).strip());
        }
        return validate(kv);
    }

    private static Config validate(Map<String, String> kv) throws ConfigException {
        if (!kv.containsKey("host") || kv.get("host").isEmpty())
            throw new ValidationConfigException("host", "required key missing");
        if (!kv.containsKey("port"))
            throw new ValidationConfigException("port", "required key missing");
        int port;
        try { port = Integer.parseInt(kv.get("port")); }
        catch (NumberFormatException e) {
            throw new ValidationConfigException("port", "'" + kv.get("port") + "' is not an integer", e);
        }
        if (port < 1 || port > 65535)
            throw new ValidationConfigException("port", port + " out of range 1-65535");
        return new Config(kv.get("host"), port);
    }
}
```

```java
// file: Main.java
public class Main {
    public static void main(String[] args) {
        try {
            var cfg = ConfigLoader.parse("app.conf");
            System.out.printf("host=%s port=%d%n", cfg.host(), cfg.port());
        } catch (ConfigLoader.IoConfigException e) {
            System.err.println("IO error: " + e.getMessage());
        } catch (ConfigLoader.ParseConfigException e) {
            System.err.println("Parse error line " + e.line + ": " + e.getMessage());
        } catch (ConfigLoader.ValidationConfigException e) {
            System.err.println("Validation error '" + e.field + "': " + e.getMessage());
        } catch (ConfigLoader.ConfigException e) {
            System.err.println("Config error: " + e.getMessage());
        }
    }
}
```

## Common Mistake

Catching all exceptions and returning a default — the cause is swallowed and the caller sees valid-looking data with no diagnostic.

```java
} catch (Exception e) {    // ✗ swallows IO, parse, and validation errors
    return new Config("", 0);  // ✗ caller sees defaults; no error surfaced
}
```
