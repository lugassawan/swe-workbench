# LSP navigation

`bin/swe-workbench-lsp` gives you a real language server's semantic index of
the codebase — the same engine behind an IDE's "Go to Definition" or "Find
All References," resolving symbols by type and scope rather than by
spelling. Reachable from `Bash` on any harness, since it never depends on a
harness-provided `LSP` tool being wired up for subagents. It exposes eight
navigation subcommands — `refs`, `def`, `impl`, `callers`, `callees`, `hover`,
`symbols`, `wsymbols` — plus `check` for availability (see below).

## It follows; it does not find

The script has no free-text search of its own — every call needs an anchor
position first. The handoff is a fixed two-step pair:

1. Search the codebase (`Grep`/`Glob`, or any equivalent text search) to
   locate the anchor — the symbol's declaration or a call site — giving you
   its file path and, ideally, its exact name.
2. Feed that anchor to the script: `swe-workbench-lsp def <file>:<line>` or
   `swe-workbench-lsp refs <file> --symbol <name>` to expand outward from it,
   or `callers`/`callees` to walk the call graph.

Text search is weakest exactly where this matters: shadowed names,
same-named methods on unrelated types, re-exports, and callers reached only
through an interface all read as text noise to a grep but resolve correctly
through the language server's semantic index.

## Availability gate — mandatory

> Run `swe-workbench-lsp check` once at the start of a task that will need
> symbol navigation — it only confirms the server binary is on `PATH`, not
> that a real handshake with your project succeeds. If the extension you need
> isn't `OK` (exit 3 from any subcommand, or `MISSING`/absent from `check`'s
> output), state `LSP unavailable — falling back to Grep` once and use Grep
> for the remainder of this run. Do not retry.
