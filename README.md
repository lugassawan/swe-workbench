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
| `clean-code` | "clean code", "function length", "naming", "DRY", "KISS", "YAGNI", "abstraction level", "error handling". |

### Languages — auto-load by file type

| Skill | Triggers |
|---|---|
| `go` | `.go` files, `go.mod`, `go.sum`, keywords: Go, Golang, goroutine, channel, context. |
| `rust` | `.rs` files, `Cargo.toml`, keywords: Rust, cargo, ownership, borrow checker, trait, lifetime. |
| `typescript` | `.ts`, `.tsx`, `.js`, `.jsx`, `package.json`, keywords: TypeScript, Node, tsconfig. |

### Workflows — auto-load during implementation

| Skill | Triggers | Delegation model |
|---|---|---|
| `development` | "implement this", "build this", "fix this bug", "execute plan", "orchestrate these issues". | Wraps the 5-phase lifecycle (Branch → Implement → Verify → Review → Deliver) around `superpowers:{using-git-worktrees, executing-plans, subagent-driven-development, test-driven-development, verification-before-completion, requesting-code-review, finishing-a-development-branch}`. Phase 4 dispatches both `superpowers:code-reviewer` (plan alignment) and the local `reviewer` subagent (diff correctness/security/design). Mode A plan template and Mode C orchestration live in companion files. |

This skill is an orchestrator — it coordinates other skills rather than restating their content.

## Philosophy

Skills are intentionally small — each under 150 lines. A sharp, well-triggered skill teaches Claude the right thing at the right moment. A giant skill burns context on material the current task does not need. If a skill grows past 150 lines, split it.

Orchestrator skills that compose many sub-skills (see Workflows) may exceed 150 lines. When they do, extract conditional content (mode templates, rarely-loaded sub-flows) into companion files inside the skill's directory rather than padding the always-loaded `SKILL.md`.

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

## Dependencies

`swe-workbench` composes with other Claude Code plugins at runtime:

| Plugin | Source | Used for | Required? |
|---|---|---|---|
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) | Process skills invoked by `development` (`using-git-worktrees`, `executing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`). | Required for the `development` skill to function end-to-end. |
| `claude-plugins-official` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Official Anthropic plugin collection — install if you need any of its bundled tools. | Optional. |

Install them via `/plugin marketplace add …` + `/plugin install …` before using the `development` skill.

## License

MIT.
