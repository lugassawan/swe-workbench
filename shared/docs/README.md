# Skill-operational reference docs

Docs a skill's *executor* needs while following that skill, on any harness — gotcha
reference material, not contributor onboarding. Shipped to installed plugins via the
npm `files` allowlist entry `shared`; `docs/` is repo-governance only and never ships.
The entry is deliberately the whole `shared/` tree, not `shared/docs`
alone: `skills/workflow-development` operatively references
`shared/agents/comment-scan.md` at runtime, so the agent/command fragment sources
ship knowingly alongside these pages (their content also ships inlined into
`agents/*.md` sentinel blocks; the copies here are the canonical sources).

- [shell-echo-vs-printf.md](shell-echo-vs-printf.md) — `echo` vs `printf` on variables holding JSON: zsh expands backslash escapes and corrupts the data.
- [gh-api-field-flags.md](gh-api-field-flags.md) — `-f` vs `-F` on `gh api`: avoid silent `@`-expansion when posting comment bodies.
- [workflow-state.md](workflow-state.md) — schema, path, and lifecycle of the workflow-state checkpoint file that survives auto-compaction.

**Adding a doc here:** it must be referenced by at least one shipped skill or command as
material the executor reads at runtime. Contributor-facing material belongs in `docs/`.
