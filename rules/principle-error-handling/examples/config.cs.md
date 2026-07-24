# Error Handling — C# — Config Parse & Validate

## Problem

C# exceptions carry an `InnerException` chain that preserves cause across tiers.
A `ConfigException` hierarchy with three subclasses — `IoConfigException`,
`ParseConfigException`, and `ValidationConfigException` — each passing `innerException`
to `base(msg, inner)`, lets callers catch at the right granularity and inspect the
full chain via `Exception.InnerException`.

## Implementation

```csharp
// file: ConfigLoader.cs
using System;
using System.Collections.Generic;
using System.IO;

public class ConfigException : Exception {
    public ConfigException(string msg, Exception? inner = null) : base(msg, inner) { }
}
public class IoConfigException : ConfigException {
    public IoConfigException(string msg, Exception inner) : base(msg, inner) { }
}
public class ParseConfigException : ConfigException {
    public int Line { get; }
    public ParseConfigException(int line, string reason)
        : base($"line {line}: {reason}") => Line = line;
}
public class ValidationConfigException : ConfigException {
    public string Field { get; }
    public ValidationConfigException(string field, string reason)
        : base($"field '{field}': {reason}") => Field = field;
}

public record Config(string Host, int Port);

public static class ConfigLoader {
    public static Config Parse(string path) {
        string[] lines;
        try {
            lines = File.ReadAllLines(path);
        } catch (Exception e) when (e is IOException or UnauthorizedAccessException) {
            throw new IoConfigException($"cannot read '{path}'", e);
        }

        var kv = new Dictionary<string, string>();
        for (int n = 0; n < lines.Length; n++) {
            var line = lines[n].Trim();
            if (line.Length == 0 || line.StartsWith('#')) continue;
            int eq = line.IndexOf('=');
            if (eq < 1)
                throw new ParseConfigException(n + 1, "missing '=' separator");
            var key = line[..eq].Trim();
            if (key.Length == 0)
                throw new ParseConfigException(n + 1, "empty key");
            kv[key] = line[(eq + 1)..].Trim();
        }
        return Validate(kv);
    }

    private static Config Validate(Dictionary<string, string> kv) {
        if (!kv.TryGetValue("host", out var host) || host.Length == 0)
            throw new ValidationConfigException("host", "required key missing");
        if (!kv.TryGetValue("port", out var portStr))
            throw new ValidationConfigException("port", "required key missing");
        if (!int.TryParse(portStr, out int port))
            throw new ValidationConfigException("port", $"'{portStr}' is not an integer");
        if (port < 1 || port > 65535)
            throw new ValidationConfigException("port", $"{port} out of range 1-65535");
        return new Config(host, port);
    }
}
```

```csharp
// file: Program.cs
try {
    var cfg = ConfigLoader.Parse("app.conf");
    Console.WriteLine($"host={cfg.Host} port={cfg.Port}");
} catch (IoConfigException e) {
    Console.Error.WriteLine($"IO error: {e.Message}");
} catch (ParseConfigException e) {
    Console.Error.WriteLine($"Parse error line {e.Line}: {e.Message}");
} catch (ValidationConfigException e) {
    Console.Error.WriteLine($"Validation error '{e.Field}': {e.Message}");
}
```

## Common Mistake

Catching `Exception` and returning a default — the inner exception is lost and the caller has no way to know what failed.

```csharp
catch (Exception) {             // ✗ swallows IoConfigException, ParseConfigException, etc.
    return new Config("", 0);   // ✗ caller sees zero Config; InnerException discarded
}
```
