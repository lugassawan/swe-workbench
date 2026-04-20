# swe-workbench

A senior-engineer toolkit for Claude Code — principled design, language expertise, and pragmatic workflows, packaged as one installable plugin.

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

## Commands

| Command | Purpose |
|---|---|
| `/swe-workbench:review` | Review the current git diff — correctness, security, design, test gaps. |
| `/swe-workbench:design <question>` | Consult the senior-engineer subagent for an architectural decision. |
| `/swe-workbench:tdd <feature>` | Run a strict red-green-refactor loop. |
| `/swe-workbench:refactor <target>` | Behavior-preserving refactor via Fowler's catalog. |

## Subagents

| Agent | When to invoke |
|---|---|
| `reviewer` | PR review, diff audit, post-feature sanity check. |
| `senior-engineer` | Architecture decisions, service scoping, tradeoff analysis. |
| `refactorer` | Cleaning up smells before adding a feature. |

## Skills

### Principles — auto-load when designing or writing code

| Skill | Triggers |
|---|---|
| `clean-architecture` | "clean architecture", "hexagonal", "ports and adapters", "dependency rule", "layering". |
| `ddd` | "DDD", "domain-driven", "bounded context", "aggregate", "value object", "ubiquitous language". |
| `solid` | "SOLID", "single responsibility", "open-closed", "Liskov", "interface segregation", "dependency inversion". |
| `tdd` | "TDD", "test-driven", "red green refactor", "unit test", "test first". |
| `design-patterns` | "design pattern", "strategy", "factory", "observer", "decorator", "adapter". |

### Languages — auto-load by file type

| Skill | Triggers |
|---|---|
| `go` | `.go` files, `go.mod`, `go.sum`, keywords: Go, Golang, goroutine, channel, context. |
| `rust` | `.rs` files, `Cargo.toml`, keywords: Rust, cargo, ownership, borrow checker, trait, lifetime. |
| `typescript` | `.ts`, `.tsx`, `.js`, `.jsx`, `package.json`, keywords: TypeScript, Node, tsconfig. |

## Philosophy

Skills are intentionally small — each under 150 lines. A sharp, well-triggered skill teaches Claude the right thing at the right moment. A giant skill burns context on material the current task does not need. If a skill grows past 150 lines, split it.

## Extending

To add a new language skill (say, Python):

1. Copy `skills/languages/go/` to `skills/languages/python/`.
2. Rewrite `SKILL.md` frontmatter: `name: python`, and a keyword-rich `description` listing `.py` files, `pyproject.toml`, and common Python terms.
3. Replace the body with the idioms that matter: error handling, typing, packaging, async, testing.
4. Keep it under 150 lines.
5. Commit; users who reinstall the plugin will pick it up.

## Testing locally

```bash
cd swe-workbench
/plugin marketplace add $(pwd)
/plugin install swe-workbench
```

Then try:

```
/swe-workbench:design "Should I use microservices for a 3-engineer team?"
/swe-workbench:review
```

If a skill does not auto-trigger, refine the `description:` in its `SKILL.md` — the description is the trigger surface.

## Contributing

After cloning, run the setup script once:

```sh
./setup.sh
```

This sets `core.hooksPath` to activate the project git hooks. The hooks enforce `[type] Subject` commit format and block accidental commits to `main`. CI (`.github/workflows/pr.yml`) runs the same checks on every pull request, so if you skip the local setup you'll just discover issues in CI instead.

Note: `.githooks/` (git hooks) is unrelated to `hooks/hooks.json` (Claude Code plugin runtime hooks) — same directory depth, different purpose.

## License

MIT.
