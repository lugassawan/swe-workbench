# Catalog

## Commands

| Command | Purpose |
|---|---|
| `/swe-workbench:review [--mode <general\|security\|a11y\|deps\|perf\|tests\|contributor-trust\|ux>]` | Review the current git diff — auditor selected by `--mode` (general, security, a11y, deps, perf, tests, contributor-trust, ux) or auto-inferred from the diff when omitted. PR number arg unchanged. |
| `/swe-workbench:security-review` | Depth-first security audit of the current diff — OWASP Top 10, secrets, insecure APIs, dependency CVEs. Pass a PR number to audit a specific PR. |
| `/swe-workbench:design <question>` | Consult the senior-engineer subagent for an architectural decision. Add `--grill` for grill-me interrogation mode (else prompts standard vs grill-me, standard recommended). |
| `/swe-workbench:architect <decision>` | Author an ADR, RFC, or cross-service contract via the architect subagent. Use when the output must be a written decision record — service decomposition, multi-system tech selection, cross-team contract — not advice about existing code. Add `--grill` for grill-me interrogation mode (else prompts standard vs grill-me, standard recommended). |
| `/swe-workbench:refactor <target>` | Behavior-preserving refactor via Fowler's catalog. |
| `/swe-workbench:migrate <description>` | Multi-deployment migration via expand → backfill → dual-write → switch → contract. Use when a single revertable commit will not do. |
| `/swe-workbench:debug <symptom>` | Diagnose a bug or failing test via systematic-debugging, then minimal fix + regression test. Add `--grill` for grill-me interrogation mode (else prompts standard vs grill-me, standard recommended). |
| `/swe-workbench:test <target> [--mode e2e \| --mode e2e-live \| --e2e]` | Default: write focused, behavioural tests in the target language's idiom. `--mode e2e`: author + run durable `@playwright/test` specs via the writer/verifier pipeline. `--mode e2e-live`: ephemeral, human-watched browser walkthrough via whichever browser MCP is connected (Playwright MCP or claude-in-chrome), optionally GIF-recorded, no spec file written. |
| `/swe-workbench:document <topic>` | Generate or update documentation (README, ADR, ARCHITECTURE, inline comments) via the tech-writer subagent. Style auto-detected from existing docs; cites commit hashes or file:line for every factual claim. |
| `/swe-workbench:implement <ticket or description>` | Drive a feature end-to-end — branch, plan, TDD build, verify, review, PR. Orchestrates the full 5-phase `workflow-development` lifecycle. Add `--grill` for grill-me interrogation mode (else prompts standard vs grill-me, standard recommended). |
| `/swe-workbench:capture <one-line thought>` | Capture an idea, bug, or improvement as a well-framed GitHub issue via the `product-manager` subagent. Auth + repo detection, product framing, duplicate scan, draft preview, and user-confirm gate before filing. Add `--grill` for grill-me interrogation mode (else prompts standard vs grill-me, standard recommended). |
| `/swe-workbench:report-issue [<one-line thought>]` | File a plugin bug or feature request directly into `lugassawan/swe-workbench` from any working directory. Mirrors `/swe-workbench:capture`'s flow but hardcodes the target repo, auto-attaches plugin + Claude Code versions, and drafts from conversation/memory when invoked with no argument. |
| `/swe-workbench:extend <sub-idea>` | Capture a mid-PR sub-idea and implement it onto the open PR's branch — no new branch, no new PR. Preserves Verify → Review → Deliver. Add `--grill` for grill-me interrogation mode (else prompts standard vs grill-me, standard recommended). |
| `/swe-workbench:address-feedback <PR number>` | Help the PR owner address review feedback — per-thread ADDRESSED/CLARIFIED/DEFERRED triage, fix application, commit, REST reply posting, and GraphQL thread resolution. |
| `/swe-workbench:audit-codebase [--time-box <dur>] [--scope <list>] [--depth <quick\|standard\|deep>]` | Cold-start, time-boxed, multi-domain defect sweep — ranked findings with reasoning chains. Use for take-home assessments, post-acquisition reviews, and tech-debt sweeps. |
| `/swe-workbench:codebase-knowledge [path]` | Present a structured knowledge document (architecture overview, module map, public API surfaces, patterns). Read-only, understanding-oriented. Distinct from `/swe-workbench:audit-codebase` (defect detection) and `/swe-workbench:document` (prose-doc generation). |
| `/swe-workbench:cleanup-merged [PR number]` | Remove the worktree, local branch, and remote branch for a merged PR. Defaults to the current branch. Squash-merge safe. |
| `/swe-workbench:sync [--rebase]` | Bring the current branch up to date with the default branch — delegates the mechanical merge/rebase to rimba (or git), then walks through any conflicts file-by-file with a `conflict-resolver` recommendation and rationale before applying. Never auto-pushes; push is a separate, prompted step. Default strategy is merge; pass `--rebase` to rebase instead. |
| `/swe-workbench:doctor` | Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude) plus gh auth status. Prints a green/red table; never modifies state. Exit 0 regardless of findings. |

## Subagents

| Agent | When to invoke |
|---|---|
| `accessibility-auditor` | Depth-first WCAG 2.2 AA review of frontend diffs — ARIA misuse, keyboard traps, focus mismanagement, color contrast. Invoked by `/swe-workbench:review --mode a11y`. |
| `architect` | Authoring ADRs, RFCs, and cross-service contracts for decisions that predate any codebase — service decomposition, multi-system tech selection, cross-team contract. Prefer over `senior-engineer` when the output must be a durable written artifact, not advice about existing code. Invoked by `/swe-workbench:architect`. |
| `auditor` | Cold-start, time-boxed, multi-domain audit sweep — security, performance, reliability, tooling, testing. Invoked by `/swe-workbench:audit-codebase`. |
| `code-impl` | Focused implementer sub-agent — receives a scoped brief (goal, file set, verify command) from the orchestrator via `swe-workbench:workflow-delegated-implementation`, implements only the assigned file group, and returns a structured summary. Never invoked directly for delivery. |
| `conflict-resolver` | Reads both sides of a merge/rebase conflict, reasons per-hunk, and recommends keep-mine/keep-main/manual with rationale. Advisory only — never edits or stages the file. Invoked per conflicting file by `swe-workbench:workflow-branch-sync` via `/swe-workbench:sync`. |
| `contributor-auditor` | Triaging external PRs for author signal, diff-shape coherence, repo posture, and pattern-risk signals before merge. Advisory only — never posts to the PR. Invoked by `/swe-workbench:review --mode contributor-trust`. |
| `debugger` | Bug diagnosis and minimal fix — composes `superpowers:systematic-debugging`, layers principle lens. |
| `dependency-auditor` | Supply-chain hygiene audit — outdated versions, license conflicts, transitive bloat, lockfile drift. Invoked by `/swe-workbench:review --mode deps`. |
| `migrator` | Plan and execute a multi-deployment migration: DB schema, framework upgrade, runtime, API/contract, or event-schema. Produces a five-phase (Expand → Backfill → Dual-write → Switch → Contract) plan with rollback gates. Invoked by `/swe-workbench:migrate`. |
| `performance-tuner` | Profile-driven hotspot triage — ranks bottlenecks from a flame graph or benchmark and recommends targeted optimizations. Refuses speculative optimization without profiling evidence. |
| `product-designer` | Depth-first UX and design quality review of frontend diffs — usability heuristics, visual hierarchy, information architecture, interaction design, design-system compliance. Invoked by `/swe-workbench:review --mode ux`. |
| `product-manager` | Drafts a well-framed GitHub issue from a raw idea — product framing (problem, value, RICE-lite), template detection, duplicate scan, and confirm gate. Invoked by `/swe-workbench:capture`. |
| `refactorer` | Cleaning up smells before adding a feature. |
| `reviewer` | PR review, diff audit, post-feature sanity check. |
| `security-auditor` | Depth-first security audit of a diff or file (OWASP Top 10, secrets, dependency CVEs). |
| `senior-engineer` | Architecture decisions, service scoping, tradeoff analysis. |
| `tech-writer` | Generates README sections, ADRs, ARCHITECTURE/OVERVIEW, and non-obvious inline comments — style-aware, reads existing docs first. Invoked by `/swe-workbench:document`. |
| `test-reviewer` | Auditing existing tests for flakiness, over-mocking, behaviour-vs-implementation drift, and coverage gaps. Invoked by `/swe-workbench:review --mode tests`. |
| `test-writer` | Authoring tests for an existing function, module, or change set. |

## Skills

### Principles — consulted by reasoning agents when relevant triggers apply

| Skill | Triggers |
|---|---|
| `principle-clean-architecture` | "clean architecture", "hexagonal", "ports and adapters", "dependency rule", "layering". |
| `principle-ddd` | "DDD", "domain-driven", "bounded context", "aggregate", "value object", "ubiquitous language". |
| `principle-solid` | "SOLID", "single responsibility", "open-closed", "Liskov", "interface segregation", "dependency inversion". |
| `principle-tdd` | "TDD", "test-driven", "red green refactor", "unit test", "test first". |
| `principle-testing` | "test pyramid", "test double", "mock", "stub", "fake", "fixture", "coverage", "mutation testing", "flaky", "contract test", "property-based test", "characterization test". |
| `principle-design-patterns` | "design pattern", "strategy", "factory", "observer", "decorator", "adapter". |
| `principle-clean-code` | "clean code", "function length", "naming", "DRY", "KISS", "YAGNI", "abstraction level", "error handling". |
| `principle-code-review` | "code review checklist", "PR review heuristics", "review comment", "review finding", "nitpick filtering", "reviewing a diff". |
| `principle-communication` | "caveman mode", "be brief", "less tokens", "use fewer tokens", "talk like caveman", "use caveman", "full caveman", "ultra caveman", "max caveman", `/caveman`, `/caveman ultra`. |
| `principle-postmortem` | "postmortem", "blameless", "root cause analysis", "5 whys", "fishbone", "incident review", "MTTD", "MTTR", "action items", "incident report", "blameless postmortem". |
| `principle-refactoring` | "refactor", "Fowler", "Extract Function", "Inline Variable", "Move Function", "smell", "Long Method", "Feature Envy", "Data Clumps", "Primitive Obsession", "characterization test", "behavior-preserving". |
| `principle-observability` | "structured logs", "application metrics", "distributed traces", "span", "OpenTelemetry", "SLO", "SLI", "RED method", "USE method", "cardinality", "structured logging". |
| `principle-api-design` | "api versioning", "idempotency", "idempotency key", "pagination", "cursor pagination", "error shape", "REST vs RPC", "event-driven", "API deprecation", "API contract". |
| `principle-event-driven` | "outbox pattern", "sagas", "choreography vs orchestration", "duplicate events", "schema evolution". |
| `principle-error-handling` | "errors as values", "Result type", "exception handling", "retry", "exponential backoff", "jitter", "circuit breaker", "fail fast", "fail soft", "idempotent retry", "error wrapping", "timeouts", "deadlines". |
| `principle-resiliency` | "bulkheads", "fail fast vs degrade gracefully", "failure domains", "readiness probes", "cascading failure". |
| `principle-concurrency` | "race condition", "deadlock", "livelock", "structured concurrency", "cancellation", "backpressure", "mutex vs channel", "actor model", "atomics", "memory model". |
| `principle-distributed-systems` | "CP vs AP", "PACELC", "Lamport timestamps", "vector clocks", "Raft". |
| `principle-performance` | "latency vs throughput", "profile before optimize", "N+1 queries", "GC pause", "Big-O". |
| `principle-cost-awareness` | "cloud cost", "FinOps", "egress", "right-sizing", "scale-to-zero", "cost-per-request", "storage tier", "log volume", "cardinality cost". |
| `principle-data-modeling` | "schema design", "data model", "normalization", "denormalization", "indexing", "hot key", "hot partition", "schema evolution", "expand contract", "query-first", "storage paradigm", "relational vs document", "TTL", "archival". |
| `principle-release-engineering` | "release", "tag", "semver", "rollout", "rollback", "kill-switch", "expand-contract", "feature flag", "release notes". |
| `principle-version-control` | "atomic commits", "rebase vs merge", "squash merge", "commit message", "trunk-based development". |
| `principle-security` | "auth", "authn", "authz", "trust boundary", "input validation", "SSRF", "CSRF", "session", "JWT", "TLS", "secret", "encrypt". |
| `principle-product-design` | "usability heuristic", "UX review", "visual hierarchy", "information architecture", "interaction design", "design system", "usability audit", "Nielsen", "loading state", "empty state", "error state", "progressive disclosure", "responsive design". |
| `principle-accessibility` | "accessibility review", "keyboard trap", "ARIA roles", "WCAG contrast", "screen reader". |
| `principle-i18n` | "locale formatting", "plural rules", "translation readiness", "right-to-left layout", "UTC in DB". |

### Languages — auto-hint by file type (subagents load deterministically)

| Skill | Triggers |
|---|---|
| `language-bash` | `.sh`, `.bash` files; keywords: bash, shell, sh, shellcheck, set -e, pipefail. |
| `language-csharp` | `.cs` files, `.csproj`, `.sln`, `Directory.Build.props`, keywords: C#, .NET, dotnet, nullable reference types, records, pattern matching, async/await, cancellation tokens, ConfigureAwait, IOptions, LINQ. |
| `language-go` | `.go` files, `go.mod`, `go.sum`, keywords: Go, Golang, goroutine, channel, context. |
| `language-java` | `.java` files, `pom.xml`, `build.gradle`, keywords: Java, JVM, Spring, Maven, Gradle, records, sealed classes, virtual threads. |
| `language-kotlin` | `.kt` files, `build.gradle.kts`, keywords: Kotlin, coroutines, suspend, StateFlow, sealed interface, Kotlin DSL. |
| `language-python` | `.py` files, `pyproject.toml`, `requirements.txt`, keywords: Python, pytest, asyncio, dataclass, type hints, virtualenv. |
| `language-ruby` | `.rb` files, `Gemfile`, `Rakefile`, gemspecs, keywords: Ruby, Bundler, RSpec, minitest, blocks, procs, lambdas, pattern matching. |
| `language-rust` | `.rs` files, `Cargo.toml`, keywords: Rust, cargo, ownership, borrow checker, trait, lifetime. |
| `language-sql` | `.sql` files, migration files; keywords: SQL, SELECT, JOIN, EXPLAIN, CTE, window function, transaction isolation, deadlock, pagination. |
| `language-swift` | `.swift` files, `Package.swift`, keywords: Swift, SwiftUI, actors, async/await, Sendable, Result builders, Swift Package Manager. |
| `language-typescript` | `.ts`, `.tsx`, `.js`, `.jsx`, `package.json`, keywords: TypeScript, Node, tsconfig. |

### Workflows — auto-hint during implementation

| Skill | Triggers | Delegation model |
|---|---|---|
| `workflow-codebase-audit` | "cold-start audit", "take-home assessment audit", "tech-debt sweep", "inherited service onboarding". | Runs a time-boxed multi-domain audit of an unfamiliar codebase. Dispatches the auditor subagent for the sweep, optionally fans out to `security-auditor` and `debugger` in deep mode, and renders ranked findings with reasoning fields. |
| `workflow-audit-emit-issues` | "file these audit findings as grouped github issues", "emit the audit results as issues grouped by subsystem", "turn the codebase audit findings into github issues". | Post-audit filing counterpart to `workflow-codebase-audit`. Groups findings by subsystem (path-prefix), discovers `.github/ISSUE_TEMPLATE/` and repo labels, renders a batch preview with `drop N`/`edit N` support, then on `confirm` files one GitHub issue per subsystem via `gh issue create --body-file`. Never fires before `confirm`. |
| `workflow-bug-triage` | "investigate this bug", "find the root cause", "file an issue for this bug", "triage this". | Investigates bugs to root cause and files a structured GitHub issue instead of patching immediately. Composes `superpowers:systematic-debugging`, enforces the no-fix-before-root-cause rule, and preview-gates the final `gh issue create`. |
| `workflow-development` | "implement this", "build this", "fix this bug", "execute plan", "orchestrate these issues". | Wraps the 5-phase lifecycle (Branch → Implement → Verify → Review → Deliver). Phase 1 prefers `rimba add <task>` when rimba is available; falls back to `superpowers:using-git-worktrees`. Phase 2 applies `swe-workbench:principle-tdd` per unit (via `superpowers:executing-plans` or `superpowers:subagent-driven-development`). Phase 3 invokes `superpowers:verification-before-completion` running **Imports → Format → Quality → Lint → Test** in order (Quality is optional, skipped with a note if no thresholds configured). Phase 4 dispatches `superpowers:requesting-code-review` (plan-alignment) and `swe-workbench:reviewer` (diff quality). Phase 5 invokes `swe-workbench:workflow-commit-and-pr`. Mode A plan template and Mode C orchestration live in companion files. |
| `workflow-commit-and-pr` | "commit this", "make a commit", "open a PR", "ship this branch". | Orchestrates preview-vs-commit-vs-ship flows, enforces the `[type] Subject` commit format, applies the docs-only `[no ci]` rule, chains ticket context when needed, and opens a draft or ready PR from the repo template. |
| `workflow-pr-review` | "review PR 123", "peer review of #456", "fetch this PR and post deduped comments". | Fetches a remote PR into an ephemeral worktree, runs the reviewer subagent with a decision footer, deduplicates against existing review threads, posts only new inline comments, and submits APPROVE or COMMENT. |
| `workflow-extend` | "/swe-workbench:extend", "extend the PR", "add this on top of the current PR", mid-PR follow-on, related sub-idea on the in-flight branch. | Captures a sub-idea inline (no new top-level issue), implements it on the same branch as the existing PR, skipping Phase 1 (Branch). Preserves Phases 2–5: Implement via TDD, Verify via `superpowers:verification-before-completion`, Review via `superpowers:requesting-code-review` + `swe-workbench:reviewer` (with scope-creep guard), Deliver via `swe-workbench:workflow-commit-and-pr` "Update existing PR" path. |
| `workflow-address-feedback` | "/swe-workbench:address-feedback", "address the feedback", "resolve review comments", "triage review threads". | PR-owner feedback loop: fetch open threads via GraphQL, per-thread A/C/D triage, fix via Edit tool, commit via `workflow-commit-and-pr`, post REST replies, resolve addressed threads via GraphQL `resolveReviewThread`. Durable worktree — no auto-cleanup. |
| `workflow-cleanup-merged` | "clean up merged branch", "remove worktree", "delete branch after merge", after a PR is merged. | Verifies merge via `gh pr view` (squash-merge safe). When rimba is available, uses `rimba remove <task>` for worktree teardown (dirty/unpushed checks included) and recommends `rimba hook install` for future automation. Without rimba, runs the `git worktree list --porcelain` safety-check path. Branch deletion and main-sync are always handled in-skill. Invoked by `/swe-workbench:cleanup-merged` and by Mode C orchestration Step 7. |
| `workflow-branch-sync` | "my branch is behind main, bring it up to date and help me resolve conflicts", "sync this branch with the default branch", "rebase my branch onto main and help me resolve conflicts". | Delegates the mechanical merge/rebase to rimba (MCP → binary → shell fallback), always passing `no_push` since rimba pushes by default and defaults to rebase — the inverse of this skill's merge-default, never-auto-push contract. On conflicts, dispatches `conflict-resolver` per file and applies the chosen side via `apply-resolution.sh`, which translates keep-mine/keep-main into git's `--ours`/`--theirs` — inverted under rebase vs merge. Leaves the result local; prompts before pushing (`--force-with-lease` only under rebase). Invoked by `/swe-workbench:sync`. |
| `workflow-codebase-knowledge` | "present this codebase as a knowledge document", "give me the architecture and module map", "explain the public API surfaces", "onboard me to this codebase", "mental model of this repo". | Read-only 5-phase sweep: Scope & entry-points → Module map → Public API surfaces → Patterns & conventions → Render. Produces a structured knowledge document with optional Mermaid diagrams (signal-to-noise rule: include only when module-graph topology adds information the table cannot convey). Not an audit — no defect ranking, no reasoning chains. Distinct from `workflow-codebase-audit` (finding-oriented) and `tech-writer` / `/swe-workbench:document` (generates new prose artifacts). Invoked by `/swe-workbench:codebase-knowledge`. |
| `workflow-pr-review-followup` | "/swe-workbench:review --check-followup", "re-check PR after fixes", "reviewer follow-up", "check if feedback was addressed". | Reviewer re-check: ephemeral worktree (`--task "pr-followup-$PR"`), reviewer agent, Jaccard ±5-line dedup, posts only truly-new inline comments, submits APPROVE/COMMENT. |
| `workflow-grill` | "--grill", "grill me", "grill-me mode", "walk the decision tree", "interrogate me on requirements". | Interrogation MODE for a scoped command's clarify step: builds a decision tree from `$ARGUMENTS` and ticket context, walks it one question at a time (recommended answer per question), self-answers codebase-answerable questions with `file:line` evidence, exits on shared understanding or "proceed" (taking recommended defaults for remaining decisions), and emits a `## Resolved decisions` block for the command to thread into its artifact step. Activated by `/swe-workbench:capture` `/swe-workbench:design` `/swe-workbench:implement` `/swe-workbench:architect` `/swe-workbench:extend` `/swe-workbench:debug`. Not a from-scratch design flow; produces no design doc. |
| `workflow-worktree-session` | "in a worktree", "open the X worktree", "move into worktree", "switch to worktree", "enter worktree", "exit the worktree", "leave worktree". | Routes to `EnterWorktree(path=…)` for existing worktrees; defers to `superpowers:using-git-worktrees` for new ones (that skill handles consent, baseline tests, and calls `EnterWorktree` itself). `ExitWorktree(action: "keep"\|"remove")` on the way out. Forbids `Bash(cd …)` as a session-switch mechanism. |
| `workflow-delegated-implementation` | "delegate this multi-module feature to focused implementer sub-agents", "group file changes and hand each cohesive changeset to code-impl", "keep orchestrator context lean by delegating implementation". | Conditional scope/complexity gate → group changes by commit-taxonomy axis (Infra/Core/Tests/Wiring) → dispatch each group to `code-impl` with a structured brief → consume the four-status summary without re-reading files → sequential default with opt-in worktree-isolated parallelism (safety table: disjoint file sets, zero cross-group dependency, no shared test target). |
| `workflow-performance-investigation` | "this endpoint is slow", "find the performance hotspot", "profile flame graph", "capture a CPU profile", "structure the investigation and add a regression guard". | Profile-first runbook: baseline → profile (per-ecosystem tooling matrix) → hand profile to `performance-tuner` for ranked hotspots → bottleneck taxonomy → one isolated change → before/after measurement → regression guard. Composes `principle-performance`. |
| `workflow-dependency-upgrade` | "upgrade our dependencies", "Dependabot PR triage", "bump this package to the latest major", "CVE patch", "major version migration and fix what breaks". | Structured upgrade runbook: triage+batch (patch/minor/major, automated vs manual) → bump & regen lockfile → build/test → breakage-triage taxonomy → PR hygiene. Per-ecosystem command matrix; composes `principle-security`. |

This skill is an orchestrator — it coordinates other skills rather than restating their content.

### Integrations — auto-hint on ticket references

| Skill | Triggers | Delegation model |
|---|---|---|
| `ticket-context` | Jira keys (`[A-Z]+-\d+`), `atlassian.net/browse/...`, Confluence wiki URLs, `github.com/.../(issues\|pull)/N`, `#N` refs. | Invoked by command bodies as a prelude before subagent delegation. Fetches via `mcp__atlassian__*` and `gh` CLI. Returns structured context (title, summary, acceptance criteria, linked refs, recent comments). Does not act on the ticket — only resolves it. |

