# Reference docs

Skill-operational reference docs — gotcha material a skill's executor needs at runtime —
live in [`shared/docs/`](../shared/docs/), which ships with the plugin via the npm `files`
allowlist. This directory is repo-governance only and never ships.

- [catalog.md](catalog.md) — commands, subagents, and skills (full tables).
- [cross-harness-handoff.md](cross-harness-handoff.md) — Claude Code ↔ Pi worktree handoff: checkpoints, leases, degraded recovery, and quota warnings.
- [extending.md](extending.md) — how to add new skills; philosophy behind the design.
- [dependencies.md](dependencies.md) — runtime plugin dependencies.
- [cost-audit.md](cost-audit.md) — point-in-time model-tier audits: initial snapshot at #160, re-tier pass at #612.
- [cost-tiers.md](cost-tiers.md) — forward-looking convention for assigning model tiers to new agents.
- [secret-detection.md](secret-detection.md) — PreToolUse hook that blocks hardcoded secrets before Write/Edit writes the file.
- [session-scratch-adapters.md](session-scratch-adapters.md) — platform-neutral session scratch cleanup: core reaper, adapter discovery/protocol, safety invariants, the Claude and Pi adapters, and how to add a new platform adapter.
- [skill-usage-telemetry.md](skill-usage-telemetry.md) — how subagent skill invocations are surfaced in the transcript.
- [worktree-permission-grant.md](worktree-permission-grant.md) — automatic permission grants for isolated worktree agents.
- [skill-preload.md](skill-preload.md) — `skills:` frontmatter preloads unconditional principle skills at dispatch; the silent-no-op trap and manual verification runbook.
- [dispatch-ledger.md](dispatch-ledger.md) — generated per-agent dispatch prefix cost snapshot (agent-body vs. preload chars, per-skill breakdown); regenerate with `scripts/dispatch-ledger.mjs --write`.
- [decisions-bin-path.md](decisions-bin-path.md) — rulings on `bin/` wrappers, PATH resolution, and plugin-local state from the bare-PATH-command migration and the `runtime/`/`bin/` collapse.
- [decisions-ci-validation.md](decisions-ci-validation.md) — why CI's validate.py gate stays open-world (no `claude plugin validate`, no frontmatter allowlist) and the golden-inventory ratchet pattern that replaces closed-form schemas.
- [decisions-hooks.md](decisions-hooks.md) — hooks.json wiring rulings (why no entry may carry an `if` condition).
- [decisions-pi-port.md](decisions-pi-port.md) — the Pi Coding Agent port: what has no Pi equivalent and why, and the framing decisions and rejected alternatives behind the whole port.
- [decisions-task-dispatch.md](decisions-task-dispatch.md) — the `task` first-party subagent dispatcher: why it isn't a `pi-subagents` fork, its recursion guards, and the model-dispatch policy.
- [decisions-runtime-envelope.md](decisions-runtime-envelope.md) — rejected alternatives behind the standard runtime result envelope.
- [decisions-cross-harness.md](decisions-cross-harness.md) — cross-harness rulings: handoff ownership (`handoff_guard.py` native mirror) and the per-repo memory stores.
- [shared-agent-blocks.md](shared-agent-blocks.md) — why `@path` includes don't expand in agent/skill/command bodies, and the sentinel-delimited inlined-block mechanism (with `sync-shared-blocks.py`) that replaced them.
