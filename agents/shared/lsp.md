# LSP navigation

`LSP` gives you a running language server's semantic index of the codebase — the same engine
behind an IDE's "Go to Definition" or "Find All References," resolving symbols by type and scope
rather than by spelling. It exposes nine operations: `goToDefinition`, `findReferences`, `hover`,
`documentSymbol`, `workspaceSymbol`, `goToImplementation`, `prepareCallHierarchy`,
`incomingCalls`, and `outgoingCalls`.

## LSP follows; it does not find

`LSP` has no free-text search of its own — every call needs an anchor position first. The handoff
is a fixed two-step pair:

1. Use `Grep`/`Glob` to locate the anchor — the symbol's declaration or a call site — giving you
   its `filePath`, `line`, and `character`.
2. Feed that anchor to `LSP`: `goToDefinition` or `findReferences` to expand outward from it, or
   `prepareCallHierarchy` followed by `incomingCalls`/`outgoingCalls` to walk the call graph.

Grep is weakest exactly where this matters: shadowed names, same-named methods on unrelated
types, re-exports, and callers reached only through an interface all read as text noise to Grep
but resolve correctly through the language server's semantic index.

## Availability gate — mandatory

> Attempt one LSP call for symbol navigation. If it returns no servers or an error, state
> `LSP unavailable — falling back to Grep` once and use Grep for the remainder of this run.
> Do not retry LSP.
