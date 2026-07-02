# Error Handling — TypeScript — Config Parse & Validate

## Problem

TypeScript has no checked exceptions, so thrown errors are typed `unknown` at catch
sites and callers cannot branch on kind without unsafe narrowing. A discriminated-union
`Result<T, E>` makes every failure explicit in the return type, forcing callers to
handle all three tiers — IO, parse, and validation — before accessing the value.

## Implementation

```typescript
// file: config.ts
import * as fs from "fs";

export type ConfigError =
  | { kind: "io"; message: string }
  | { kind: "parse"; line: number; message: string }
  | { kind: "validation"; message: string };

type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export interface Config { host: string; port: number }

export function parseConfig(path: string): Result<Config, ConfigError> {
  let text: string;
  try {
    text = fs.readFileSync(path, "utf8");
  } catch (e) {
    return { ok: false, error: { kind: "io", message: String(e) } };
  }

  const kv: Record<string, string> = {};
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 1) {
      return { ok: false, error: { kind: "parse", line: i + 1,
        message: "malformed line, expected key=value" } };
    }
    const key = line.slice(0, eq).trim();
    if (!key) {
      return { ok: false, error: { kind: "parse", line: i + 1,
        message: "empty key" } };
    }
    kv[key] = line.slice(eq + 1).trim();
  }

  return validate(kv);
}

function validate(kv: Record<string, string>): Result<Config, ConfigError> {
  if (!kv["host"]) return { ok: false, error: { kind: "validation",
    message: "missing required key: host" } };
  if (!kv["port"]) return { ok: false, error: { kind: "validation",
    message: "missing required key: port" } };
  const port = Number(kv["port"]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { ok: false, error: { kind: "validation",
      message: `port '${kv["port"]}' must be an integer 1-65535` } };
  }
  return { ok: true, value: { host: kv["host"], port } };
}
```

```typescript
// file: main.ts
import { parseConfig } from "./config";

const result = parseConfig("app.conf");
if (!result.ok) {
  const e = result.error;
  if (e.kind === "io")         console.error("IO error:", e.message);
  else if (e.kind === "parse") console.error(`Parse error line ${e.line}:`, e.message);
  else                         console.error("Validation error:", e.message);
  process.exit(1);
}
console.log(`host=${result.value.host} port=${result.value.port}`);
```

## Common Mistake

Returning `null` on failure — callers get no error kind, no message, and cannot distinguish IO from validation failures.

```typescript
function parseConfig(path: string): Config | null {
  try { /* ... */ }
  catch { return null; }  // ✗ all three error tiers collapsed to null — undiagnosable
}
```
