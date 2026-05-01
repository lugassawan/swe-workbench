# SWE Workbench

*A senior engineer's toolkit for Claude Code — principled design, language expertise, pragmatic workflows.*

## What it is

`swe-workbench` bundles the reasoning a careful senior engineer does every day: architectural judgement (Clean Architecture, DDD, SOLID), test discipline (TDD, F.I.R.S.T.), pattern fluency (GoF and beyond), and idiomatic expertise in Go, Rust, and TypeScript. Principles auto-load when you are designing or writing code; language skills auto-load by file extension; commands and subagents are there when you want explicit help.

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

- **Commands** — `/swe-workbench:review`, `/swe-workbench:design`, `/swe-workbench:refactor`, `/swe-workbench:debug`, `/swe-workbench:implement`, `/swe-workbench:test`, `/swe-workbench:security-review` — see [docs/catalog.md](docs/catalog.md).
- **Subagents** — `reviewer`, `senior-engineer`, `refactorer`, `debugger`, `security-auditor`, `test-writer` — see [docs/catalog.md](docs/catalog.md).
- **Principles** — Clean Architecture, DDD, SOLID, TDD, design patterns, clean code, observability, API design, concurrency — auto-load by trigger keyword.
- **Languages** — Go, Rust, TypeScript — auto-load by file extension.
- **Integrations** — `ticket-context` — auto-loads on ticket references (Jira, Confluence, GitHub) to feed the full spec into commands.
- **Workflows** — `development` orchestrator wrapping the full 5-phase implementation lifecycle.

Full reference tables → [docs/catalog.md](docs/catalog.md). Extending guide and philosophy → [docs/extending.md](docs/extending.md). Runtime dependencies → [docs/dependencies.md](docs/dependencies.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT.
