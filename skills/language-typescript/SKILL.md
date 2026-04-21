---
name: language-typescript
description: TypeScript and JavaScript idioms — strict mode, type safety, discriminated unions, async patterns, and Node. Auto-load when working with .ts, .tsx, .js, .jsx files, package.json, or when the user mentions TypeScript, JavaScript, Node, type safety, or tsconfig.
---

# TypeScript / JavaScript

## Strict mode or nothing
Enable in `tsconfig.json`:

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "exactOptionalPropertyTypes": true
  }
}
```

Without these, types lie.

## Prefer `unknown` over `any`
`any` turns off the type system. `unknown` forces narrowing.

```ts
function parse(input: unknown): User {
  if (!isUser(input)) throw new Error("invalid user");
  return input;
}
```

## Discriminated unions over enums
Enums have runtime quirks and poor exhaustiveness. Use string-literal unions with a discriminant.

```ts
type Event =
  | { kind: "click"; x: number; y: number }
  | { kind: "submit"; form: FormData };

function handle(e: Event) {
  switch (e.kind) {
    case "click":  return trackClick(e.x, e.y);
    case "submit": return submit(e.form);
    default: {
      const _exhaustive: never = e; return _exhaustive;
    }
  }
}
```

## Branded types for domain primitives
Stop `UserId` from being passed where an `OrderId` is expected.

```ts
type Brand<K, T> = K & { readonly __brand: T };
type UserId = Brand<string, "UserId">;
type OrderId = Brand<string, "OrderId">;
const makeUserId = (s: string): UserId => s as UserId;
```

## Async patterns
- `await` everything that returns a promise. Floating promises silently swallow errors.
- Enable `@typescript-eslint/no-floating-promises`.
- `Promise.all` for all-or-fail; `Promise.allSettled` when partial failure is acceptable.
- Don't mix `.then()` chains with `await` in the same function.
- Timeouts belong on every external call. `AbortController` is the standard.

```ts
const ac = new AbortController();
const t = setTimeout(() => ac.abort(), 5_000);
try {
  const r = await fetch(url, { signal: ac.signal });
  return await r.json();
} finally {
  clearTimeout(t);
}
```

## Structural typing gotchas
TypeScript types are shapes, not identities. Two unrelated types with the same fields are interchangeable. Brand when you need nominal behavior.

## Error handling
- Throw `Error` subclasses, not strings.
- Catch `unknown` at boundaries; narrow before use.
- For domain code, consider `Result<T, E>`-style unions over throwing — explicit, typed, exhaustively handled.

## Modules and imports
- ESM (`"type": "module"`) in new projects.
- Absolute imports via `paths` in `tsconfig`; don't ship `../../../` ladders.
- Keep barrels (`index.ts`) shallow — deep barrels slow cold-start and break tree-shaking.

## React / TSX notes
- `ReactNode` for children props. `JSX.Element` is narrower than you usually want.
- Avoid `FC<Props>` — it adds implicit `children` and breaks generic components. Prefer `function Thing(props: Props) { ... }`.
- `useEffect` only for synchronizing with external systems. Derived state belongs in render.

## Testing
- Vitest or Jest — pick one.
- `tsd` or `expectType` for type-level tests of public APIs.
- Avoid snapshot tests of implementation details.

## Avoid
- `any`, `// @ts-ignore`, `as unknown as T` in production code.
- Non-null assertions (`!`) without a comment explaining why.
- `Object`, `Function`, `{}` as types — they are never what you want.
- Classes where a function and a closure would do.
