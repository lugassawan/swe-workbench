# Reference docs

- [catalog.md](catalog.md) — commands, subagents, and skills (full tables).
- [extending.md](extending.md) — how to add new skills; philosophy behind the design.
- [dependencies.md](dependencies.md) — runtime plugin dependencies.
- [cost-audit.md](cost-audit.md) — point-in-time model-tier audit (snapshot at #160).
- [cost-tiers.md](cost-tiers.md) — forward-looking convention for assigning model tiers to new agents.
- [secret-detection.md](secret-detection.md) — PreToolUse hook that blocks hardcoded secrets before Write/Edit writes the file.
- [workflow-state.md](workflow-state.md) — SessionStart hook that persists workflow phase state across auto-compaction and injects a resume preamble.
