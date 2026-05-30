# SWE Workbench

*A senior engineer's toolkit for Claude Code — principled design, language expertise, pragmatic workflows.*

## What it is

`swe-workbench` bundles the reasoning a careful senior engineer does every day: architectural judgement (Clean Architecture, DDD, SOLID), test discipline (TDD, F.I.R.S.T.), pattern fluency (GoF and beyond), and idiomatic expertise in Bash, C#, Go, Java, Kotlin, Python, Ruby, Rust, SQL, Swift, and TypeScript. Principle and language skills auto-hint by trigger (a non-blocking hint fires when a matching file is touched); commands and subagents are there when you want explicit help.

## Install

From the marketplace:

```
/plugin marketplace add lugassawan/swe-workbench
/plugin install swe-workbench
```

For local development:

```
git clone https://github.com/lugassawan/swe-workbench
cd swe-workbench
/plugin marketplace add $(pwd)
/plugin install swe-workbench
```

## What's inside

- **Commands** — `/swe-workbench:review`, `/swe-workbench:design`, `/swe-workbench:architect`, `/swe-workbench:document`, `/swe-workbench:refactor`, `/swe-workbench:migrate`, `/swe-workbench:debug`, `/swe-workbench:implement`, `/swe-workbench:extend`, `/swe-workbench:test`, `/swe-workbench:security-review`, `/swe-workbench:capture`, `/swe-workbench:report-issue`, `/swe-workbench:cleanup-merged`, `/swe-workbench:address-feedback`, `/swe-workbench:audit-codebase`, `/swe-workbench:codebase-knowledge`, `/swe-workbench:doctor` — see [docs/catalog.md](docs/catalog.md).
- **Subagents** — `accessibility-auditor`, `architect`, `auditor`, `code-impl`, `contributor-auditor`, `debugger`, `dependency-auditor`, `migrator`, `performance-tuner`, `product-manager`, `refactorer`, `reviewer`, `security-auditor`, `senior-engineer`, `tech-writer`, `test-reviewer`, `test-writer` — see [docs/catalog.md](docs/catalog.md).
- **Principles** — Clean Architecture, DDD, SOLID, TDD, design patterns, clean code, observability, API design, concurrency, data modeling, error handling, security — auto-hint by trigger keyword.
- **Languages** — Bash, C#, Go, Java, Kotlin, Python, Ruby, Rust, SQL, Swift, TypeScript — auto-hint by file extension (subagents load deterministically via catalog injection).
- **Integrations** — `ticket-context` — auto-loads on ticket references (Jira, Confluence, GitHub) to feed the full spec into commands.
- **Workflows** — `development` orchestrator wrapping the full 5-phase implementation lifecycle.

Full reference tables → [docs/catalog.md](docs/catalog.md). Extending guide and philosophy → [docs/extending.md](docs/extending.md). Runtime dependencies → [docs/dependencies.md](docs/dependencies.md).

## Secret detection

Every `Write` and `Edit` tool call is scanned for hardcoded secrets (GitHub
tokens, AWS keys, `.env`-style assignments) before the file is written.
Detected secrets are blocked with a `BLOCKED:` message naming the pattern,
line number, and file. Use `# nosecret` on a line to suppress intentional
fixtures. See [docs/secret-detection.md](docs/secret-detection.md) for the
full pattern list, suppression options, and security notes.

## Workflow state persistence

When Claude Code auto-compacts a long conversation, any in-progress `workflow-development`,
`workflow-bug-triage`, or `workflow-pr-review` state is saved to a sidecar JSON file under
`.claude/cache/workflow-state/`. A `SessionStart` hook detects this file after compaction
and injects a resume preamble so the workflow continues at the correct phase — no manual
restart needed. See [docs/workflow-state.md](docs/workflow-state.md) for the schema,
lifecycle table, and a manual smoke test.

## Skill-usage telemetry

When the orchestrator dispatches a subagent, the skills that subagent invokes are surfaced in the transcript:

```
Skills used by reviewer: swe-workbench:principle-code-review, swe-workbench:principle-clean-code
```

Top-level skill calls and zero-skill runs produce no output. Individual agents can opt out via `skill_telemetry: false` in their frontmatter. See [docs/skill-usage-telemetry.md](docs/skill-usage-telemetry.md) for full details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT.

- [workflow-state.md](workflow-state.md) — SessionStart hook that persists workflow phase state across auto-compaction and injects a resume preamble.
- [skill-usage-telemetry.md](skill-usage-telemetry.md) — how subagent skill invocations are surfaced in the transcript.
- [worktree-permission-grant.md](worktree-permission-grant.md) — automatic permission grants for isolated worktree agents.
