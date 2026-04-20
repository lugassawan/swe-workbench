# Catalog

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
