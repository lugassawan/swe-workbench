# Reference docs

- [catalog.md](catalog.md) — commands, subagents, and skills (full tables).
- [extending.md](extending.md) — how to add new skills; philosophy behind the design.
- [dependencies.md](dependencies.md) — runtime plugin dependencies.
- [cost-audit.md](cost-audit.md) — point-in-time model-tier audits: initial snapshot at #160, re-tier pass at #612.
- [cost-tiers.md](cost-tiers.md) — forward-looking convention for assigning model tiers to new agents.
- [secret-detection.md](secret-detection.md) — PreToolUse hook that blocks hardcoded secrets before Write/Edit writes the file.
- [workflow-state.md](workflow-state.md) — SessionStart hook that persists workflow phase state across auto-compaction and injects a resume preamble.
- [skill-usage-telemetry.md](skill-usage-telemetry.md) — how subagent skill invocations are surfaced in the transcript.
- [worktree-permission-grant.md](worktree-permission-grant.md) — automatic permission grants for isolated worktree agents.
- [gh-api-field-flags.md](gh-api-field-flags.md) — `-f` vs `-F` on `gh api`: avoid silent `@`-expansion when posting comment bodies.
- [shell-echo-vs-printf.md](shell-echo-vs-printf.md) — `echo` vs `printf` on variables holding JSON: zsh expands backslash escapes and corrupts the data.
- [skill-preload.md](skill-preload.md) — `skills:` frontmatter preloads unconditional principle skills at dispatch; the silent-no-op trap and manual verification runbook.
- [plugin-platform-decisions.md](plugin-platform-decisions.md) — rulings from the bare-PATH-command migration and the `runtime/`/`bin/` collapse (why `CLAUDE_PLUGIN_DATA` wasn't adopted, why CI has no closed-world plugin-schema validator, the `bin/` dev-loop caveat), and from porting the plugin to the Pi Coding Agent (§6 onward) — what has no Pi equivalent and why, and the framing decisions and rejected alternatives behind the whole port (§10).
- [shared-agent-blocks.md](shared-agent-blocks.md) — why `@path` includes don't expand in agent/skill/command bodies, and the sentinel-delimited inlined-block mechanism (with `sync-shared-blocks.py`) that replaced them.
