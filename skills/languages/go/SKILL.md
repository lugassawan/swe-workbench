---
name: go
description: Go idioms, error handling, concurrency, and standard library usage. Auto-load when working with .go files, go.mod, go.sum, or when the user mentions Go, Golang, goroutines, channels, interfaces, context, or error wrapping.
---

# Go

## Errors are values
- Return `error`; do not `panic` across package boundaries.
- Wrap with `fmt.Errorf("doing X: %w", err)` to preserve the chain.
- Inspect with `errors.Is` and `errors.As`. Never string-match messages.
- Sentinel errors (`var ErrNotFound = errors.New(...)`) for expected cases; typed errors when callers need structured data.

```go
if err != nil {
    return fmt.Errorf("load user %s: %w", id, err)
}
```

## Interfaces — small, defined by the consumer
- Define interfaces in the package that *uses* them, not where concrete types live.
- Single-method interfaces are normal (`io.Reader`, `io.Closer`).
- Accept interfaces, return concrete types.

## Concurrency
- A goroutine without a known termination path is a leak. Always know who stops it.
- `context.Context` plumbs cancellation and deadlines — first parameter, named `ctx`.
- Channels for ownership transfer; mutexes for protecting state. A `sync.Mutex` is often simpler than a goroutine.
- `errgroup.Group` for structured concurrency with error propagation.

```go
g, ctx := errgroup.WithContext(ctx)
for _, job := range jobs {
    job := job
    g.Go(func() error { return process(ctx, job) })
}
if err := g.Wait(); err != nil { return err }
```

## Context rules
- `ctx` is the first parameter of any blocking or IO function.
- Never store `context.Context` in a struct field.
- Don't use `context.Value` for required parameters — only cross-cutting concerns like request IDs.

## Tests
- Table-driven tests are the default.
- `t.Run(name, ...)` for subtests.
- `t.Cleanup` beats `defer` for shared fixtures.
- `httptest.Server` for HTTP; `testing/iotest` for edge IO.

```go
for _, c := range cases {
    t.Run(c.name, func(t *testing.T) {
        if got := Add(c.a, c.b); got != c.want {
            t.Errorf("Add(%d,%d) = %d, want %d", c.a, c.b, got, c.want)
        }
    })
}
```

## Package design
- Package name = its purpose, lower-case, no underscores.
- Avoid `util`, `common`, `helpers`. Name by the domain thing it owns.
- Cyclic imports are a design smell — break with an interface in the consuming package.

## Idioms cheat sheet
- `if err := do(); err != nil { ... }` — keep errors close to their cause.
- Zero values are useful — design types so zero works.
- `defer` for cleanup; `defer` in a loop accumulates.
- Exported fields beat getters/setters unless behavior needs them.
- `any` over `interface{}` in new code.
- Prefer `slices`, `maps`, `cmp` from stdlib over hand-rolled helpers.

## Avoid
- Naked returns outside tiny functions.
- `panic` as flow control.
- Empty interfaces in public APIs without a strong reason.
- Over-generics — use them only when they clearly reduce duplication.
