# Catalog

## Commands

| Command | Purpose |
|---|---|
| `/swe-workbench:review` | Review the current git diff — correctness, security, design, test gaps. |
| `/swe-workbench:security-review` | Audit the current git diff for security vulnerabilities — OWASP Top 10, secrets, insecure APIs. |
| `/swe-workbench:design <question>` | Consult the senior-engineer subagent for an architectural decision. |
| `/swe-workbench:refactor <target>` | Behavior-preserving refactor via Fowler's catalog. |
| `/swe-workbench:debug <symptom>` | Diagnose a bug or failing test via systematic-debugging, then minimal fix + regression test. |
| `/swe-workbench:test <target>` | Write focused, behavioural tests in the target language's idiom. |
| `/swe-workbench:implement <ticket or description>` | Drive a feature end-to-end — branch, plan, TDD build, verify, review, PR. Orchestrates the full 5-phase `workflow-development` lifecycle. |

## Subagents

| Agent | When to invoke |
|---|---|
| `reviewer` | PR review, diff audit, post-feature sanity check. |
| `security-auditor` | Depth-first security audit of a diff or file (OWASP Top 10, secrets, dependency CVEs). |
| `senior-engineer` | Architecture decisions, service scoping, tradeoff analysis. |
| `refactorer` | Cleaning up smells before adding a feature. |
| `debugger` | Bug diagnosis and minimal fix — composes `superpowers:systematic-debugging`, layers principle lens. |
| `test-writer` | Authoring tests for an existing function, module, or change set. |

## Skills

### Principles — auto-load when designing or writing code

| Skill | Triggers |
|---|---|
| `principle-clean-architecture` | "clean architecture", "hexagonal", "ports and adapters", "dependency rule", "layering". |
| `principle-ddd` | "DDD", "domain-driven", "bounded context", "aggregate", "value object", "ubiquitous language". |
| `principle-solid` | "SOLID", "single responsibility", "open-closed", "Liskov", "interface segregation", "dependency inversion". |
| `principle-tdd` | "TDD", "test-driven", "red green refactor", "unit test", "test first". |
| `principle-design-patterns` | "design pattern", "strategy", "factory", "observer", "decorator", "adapter". |
| `principle-clean-code` | "clean code", "function length", "naming", "DRY", "KISS", "YAGNI", "abstraction level", "error handling". |
| `principle-observability` | "structured logs", "application metrics", "distributed traces", "span", "OpenTelemetry", "SLO", "SLI", "RED method", "USE method", "cardinality", "structured logging". |
| `principle-api-design` | "api versioning", "idempotency", "idempotency key", "pagination", "cursor pagination", "error shape", "REST vs RPC", "event-driven", "API deprecation", "API contract". |
| `principle-error-handling` | "errors as values", "Result type", "exception handling", "retry", "exponential backoff", "jitter", "circuit breaker", "fail fast", "fail soft", "idempotent retry", "error wrapping", "timeouts", "deadlines". |
| `principle-concurrency` | "race condition", "deadlock", "livelock", "structured concurrency", "cancellation", "backpressure", "mutex vs channel", "actor model", "atomics", "memory model". |
| `principle-security` | "auth", "authn", "authz", "trust boundary", "input validation", "SSRF", "CSRF", "session", "JWT", "TLS", "secret", "encrypt". |

### Languages — auto-load by file type

| Skill | Triggers |
|---|---|
| `language-go` | `.go` files, `go.mod`, `go.sum`, keywords: Go, Golang, goroutine, channel, context. |
| `language-rust` | `.rs` files, `Cargo.toml`, keywords: Rust, cargo, ownership, borrow checker, trait, lifetime. |
| `language-typescript` | `.ts`, `.tsx`, `.js`, `.jsx`, `package.json`, keywords: TypeScript, Node, tsconfig. |

### Workflows — auto-load during implementation

| Skill | Triggers | Delegation model |
|---|---|---|
| `workflow-development` | "implement this", "build this", "fix this bug", "execute plan", "orchestrate these issues". | Wraps the 5-phase lifecycle (Branch → Implement → Verify → Review → Deliver) around `superpowers:{using-git-worktrees, executing-plans, subagent-driven-development, test-driven-development, verification-before-completion, requesting-code-review, finishing-a-development-branch}`. Phase 4 dispatches both `superpowers:code-reviewer` (plan alignment) and the local `reviewer` subagent (diff correctness/security/design). Mode A plan template and Mode C orchestration live in companion files. |

This skill is an orchestrator — it coordinates other skills rather than restating their content.

### Integrations — auto-load on ticket references

| Skill | Triggers | Delegation model |
|---|---|---|
| `ticket-context` | Jira keys (`[A-Z]+-\d+`), `atlassian.net/browse/...`, Confluence wiki URLs, `github.com/.../(issues\|pull)/N`, `#N` refs. | Invoked by command bodies as a prelude before subagent delegation. Fetches via `mcp__atlassian__*` and `gh` CLI. Returns structured context (title, summary, acceptance criteria, linked refs, recent comments). Does not act on the ticket — only resolves it. |

