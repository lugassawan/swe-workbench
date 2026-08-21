# Shared agent-body fragments: why `@path` includes don't work here

`@path` references expand in exactly two places: CLAUDE.md memory imports, and interactive user
prompts. They are **not** expanded inside an agent (`agents/*.md`), skill (`skills/*/SKILL.md`),
or command (`commands/*.md`) body. A dispatched subagent receives the literal `@path` text — it
never sees the referenced file's content.

## The incident

All 22 `agents/*.md` files used `@../shared/agents/<fragment>.md`-style includes, expecting them
to resolve to real content at dispatch time. They never did. Every agent silently ran without the
shared behavioral-contract text it was written to depend on, for a long time before this was
noticed and fixed. The pre-existing test suite didn't catch this because it asserted the include
*string* was present in the agent file — never that the referenced content actually reached the
dispatched agent.

## The fix

Shared fragments under `shared/agents/*.md` are inlined into every consuming file as real,
byte-identical text between a pair of HTML-comment sentinels:

```markdown
<!-- BEGIN shared/agents/lsp.md -->
…verbatim content of shared/agents/lsp.md…
<!-- END shared/agents/lsp.md -->
```

`scripts/sync-shared-blocks.py` fills and checks these blocks (`--write` / `--check`).
`scripts/validate.py`'s `check_shared_blocks_in_sync()` enforces byte-identical parity between
every inlined block and its source on every `bash scripts/validate.sh` run — someone hand-editing
an inlined block, or editing the source and forgetting to re-sync, fails the check either way. See
CONTRIBUTING.md's "Adding a shared agent-body fragment reference" for the authoring recipe.

## The rule going forward

Never add a bare `@../shared/...` or `@./shared/...` reference anywhere in `agents/`, `commands/`,
or `skills/` expecting it to resolve — it won't. `scripts/validate.py`'s
`check_no_inert_at_includes()` rejects any such reference on sight, so this specific dead pattern
can't quietly reappear.
