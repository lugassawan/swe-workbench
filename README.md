# SWE Workbench

*A senior engineer's toolkit for Claude Code — principled design, language expertise, pragmatic workflows.*

## What it is

`swe-workbench` bundles the reasoning a careful senior engineer does every day: architectural judgement (Clean Architecture, DDD, SOLID), test discipline (TDD, F.I.R.S.T.), pattern fluency (GoF and beyond), and idiomatic expertise in Bash, C#, Dart, Go, Java, Kotlin, Python, Ruby, Rust, SQL, Swift, and TypeScript. Principle and language skills auto-hint by trigger (a non-blocking hint fires when a matching file is touched); commands and subagents are there when you want explicit help.

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

For the [Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent) (a separate harness from Claude Code — not a `/plugin` install):

```
pi install git:github.com/lugassawan/swe-workbench
```

This loads the same `skills/`, `commands/`, and `agents/` trees Claude Code uses, via the runtime adapter in `pi/extensions/`. See `docs/plugin-platform-decisions.md` for the Pi-specific rulings.

## What's inside

- **Commands** — `/swe-workbench:review`, `/swe-workbench:design`, `/swe-workbench:architect`, `/swe-workbench:document`, `/swe-workbench:refactor`, `/swe-workbench:migrate`, `/swe-workbench:debug`, `/swe-workbench:implement`, `/swe-workbench:hotfix`, `/swe-workbench:extend`, `/swe-workbench:test`, `/swe-workbench:security-review`, `/swe-workbench:capture`, `/swe-workbench:report-issue`, `/swe-workbench:cleanup-merged`, `/swe-workbench:sync`, `/swe-workbench:address-feedback`, `/swe-workbench:audit-codebase`, `/swe-workbench:codebase-knowledge`, `/swe-workbench:doctor`, `/swe-workbench:converge` — see [docs/catalog.md](docs/catalog.md).
- **Subagents** — `swe-workbench:accessibility-auditor`, `swe-workbench:architect`, `swe-workbench:auditor`, `swe-workbench:code-impl`, `swe-workbench:conflict-resolver`, `swe-workbench:contributor-auditor`, `swe-workbench:debugger`, `swe-workbench:dependency-auditor`, `swe-workbench:e2e-test-verifier`, `swe-workbench:e2e-test-writer`, `swe-workbench:migrator`, `swe-workbench:performance-tuner`, `swe-workbench:product-designer`, `swe-workbench:product-manager`, `swe-workbench:redundancy-assessor`, `swe-workbench:refactorer`, `swe-workbench:reviewer`, `swe-workbench:security-auditor`, `swe-workbench:senior-engineer`, `swe-workbench:tech-writer`, `swe-workbench:test-reviewer`, `swe-workbench:test-writer` — see [docs/catalog.md](docs/catalog.md).
- **Principles** — Clean Architecture, DDD, SOLID, TDD, design patterns, clean code, observability, API design, concurrency, data modeling, error handling, security, product design — auto-hint by trigger keyword.
- **Languages** — Bash, C#, Dart, Go, Java, Kotlin, Python, Ruby, Rust, SQL, Swift, TypeScript — auto-hint by file extension (subagents load deterministically via catalog injection).
- **Integrations** — external-service context skills (`swe-workbench:ticket-context`, `swe-workbench:observability-context`, `swe-workbench:comms-context`) — auto-load on ticket references, Sentry links, Slack/PagerDuty links to feed the full context into commands — see [docs/catalog.md](docs/catalog.md).
- **Workflows** — `development` orchestrator wrapping the full 5-phase implementation lifecycle; `swe-workbench:workflow-audit-emit-issues` files grouped GitHub issues from codebase audit findings.

Full reference tables → [docs/catalog.md](docs/catalog.md). Extending guide and philosophy → [docs/extending.md](docs/extending.md). Runtime dependencies → [docs/dependencies.md](docs/dependencies.md).

## Secret detection

Every `Write` and `Edit` tool call is scanned for hardcoded secrets (GitHub
tokens, AWS keys, `.env`-style assignments) before the file is written.
Detected secrets are blocked with a `BLOCKED:` message naming the pattern,
line number, and file. Use `# nosecret` on a line to suppress intentional
fixtures. See [docs/secret-detection.md](docs/secret-detection.md) for the
full pattern list, suppression options, and security notes.

## Workflow state persistence

When Claude Code auto-compacts a long conversation, any in-progress `swe-workbench:workflow-development`,
`swe-workbench:workflow-bug-triage`, or `swe-workbench:workflow-pr-review` state is saved to a sidecar JSON file under
`.claude/cache/workflow-state/`. A `SessionStart` hook detects this file and injects a
resume preamble so the workflow continues at the correct phase — no manual restart needed.
The hook fires on compaction as well as on plain session startup/resume, and also nudges a
worktree re-anchor when the session's cwd has drifted from a linked worktree. See
[shared/docs/workflow-state.md](shared/docs/workflow-state.md) for the schema, lifecycle table, and a
manual smoke test.

`.claude/cache/` is this repo's ephemeral-state directory — add it to your own repo's
`.gitignore` when installing swe-workbench, or these sidecars become committable.
`/swe-workbench:doctor` checks for this and warns if it's missing.

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
