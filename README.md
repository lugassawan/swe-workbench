# SWE Workbench

*A senior engineer's toolkit for Claude Code — principled design, language expertise, pragmatic workflows.*

## What it is

`swe-workbench` bundles the reasoning a careful senior engineer does every day: architectural judgement (Clean Architecture, DDD, SOLID), test discipline (TDD, F.I.R.S.T.), pattern fluency (GoF and beyond), and idiomatic expertise in Bash, Go, Java, Kotlin, Python, Rust, Swift, and TypeScript. Principles auto-load when you are designing or writing code; language skills auto-load by file extension; commands and subagents are there when you want explicit help.

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

- **Commands** — `/swe-workbench:review`, `/swe-workbench:design`, `/swe-workbench:refactor`, `/swe-workbench:migrate`, `/swe-workbench:debug`, `/swe-workbench:implement`, `/swe-workbench:extend`, `/swe-workbench:test`, `/swe-workbench:security-review`, `/swe-workbench:capture`, `/swe-workbench:cleanup-merged` — see [docs/catalog.md](docs/catalog.md).
- **Subagents** — `accessibility-auditor`, `architect`, `auditor`, `debugger`, `dependency-auditor`, `migrator`, `performance-tuner`, `product-manager`, `refactorer`, `reviewer`, `security-auditor`, `senior-engineer`, `tech-writer`, `test-writer` — see [docs/catalog.md](docs/catalog.md).
- **Principles** — Clean Architecture, DDD, SOLID, TDD, design patterns, clean code, observability, API design, concurrency, data modeling, error handling, security — auto-load by trigger keyword.
- **Languages** — Bash, Go, Java, Kotlin, Python, Rust, Swift, TypeScript — auto-load by file extension.
- **Integrations** — `ticket-context` — auto-loads on ticket references (Jira, Confluence, GitHub) to feed the full spec into commands.
- **Workflows** — `development` orchestrator wrapping the full 5-phase implementation lifecycle.

Full reference tables → [docs/catalog.md](docs/catalog.md). Extending guide and philosophy → [docs/extending.md](docs/extending.md). Runtime dependencies → [docs/dependencies.md](docs/dependencies.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT.
