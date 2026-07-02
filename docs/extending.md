# Extending

## Adding a language skill

To add a new language skill (say, Ruby or another language not already shipped):

1. Copy `skills/language-go/` to `skills/language-<your-language>/`.
2. Rewrite `SKILL.md` frontmatter: `name: language-<your-language>`, and a keyword-rich `description` listing the language's file types and ecosystem terms.
3. Replace the body with the idioms that matter: error handling, typing, packaging, async, testing.
4. Keep it under 150 lines.
5. Add an entry to `agents/shared/languages.md` (the language slice of the skill catalog) — see CONTRIBUTING.md for the required format and how the validator enforces it.
6. Commit; users who reinstall the plugin will pick it up.

## Philosophy

Skills are intentionally small — each under 150 lines. A sharp, well-triggered skill teaches Claude the right thing at the right moment. A giant skill burns context on material the current task does not need. If a skill grows past 150 lines, split it.

Orchestrator skills that compose many sub-skills (see the `development` workflow) may exceed 150 lines. When they do, extract conditional content (mode templates, rarely-loaded sub-flows) into companion files inside the skill's directory rather than padding the always-loaded `SKILL.md`.

## Dependency flow

Three artifact kinds — commands, skills, and agents — form a strict layering:

```
command ──► skill ──► skill
   │         │
   │         ▼
   └───────► agent ──► skill
```

**Commands** are orchestrators (top layer). A command pulls in whatever skills and subagents a workflow needs. Commands may activate skills and agents.

**Skills** may activate other skills. Composing a workflow from smaller skills is encouraged; it keeps any single skill under the 150-line cap (see `## Philosophy`). Skills must not activate commands.

**Agents** may activate skills. An agent is a leaf worker dispatched *by* a command, never the reverse. Naming the entry command in a `**Reachable via:**` breadcrumb is documentation, not a dependency, and does not count as an activation.

**Async handoffs:** a skill may suggest running a command as a human-driven next step (e.g. "run `/swe-workbench:review` next"). This is an asynchronous handoff — the user decides whether to follow up — not a synchronous activation, and does not form a loading cycle.

**No back-edges:** nothing that a command activates may synchronously activate that command (or its skills) in turn. Cycles in the activation graph break Claude Code's loading behavior and are forbidden at all layers.

`scripts/validate.py` (`check_no_cycles`) machine-enforces the no-cycle rule by scanning action-cued `` `swe-workbench:<id>` `` activations. Slash-command handoffs (`/swe-workbench:cmd`) and prose cross-references (`` See `swe-workbench:X` ``) are intentionally excluded from the graph — they are pointers, not activations.

## Adding worked examples to a skill

For skills that describe patterns (e.g. `principle-*`), add language-specific implementations as companion files in an `examples/` subdirectory inside the skill's directory:

```
skills/principle-clean-architecture/
├── SKILL.md
└── examples/
    ├── mvc.go.md
    ├── mvc.java.md
    └── mvc.ts.md
```

**Loading model:** examples are never auto-loaded. `SKILL.md` holds an explicit pointer (e.g. `> See examples/ for worked implementations.`). The agent or user reads them on demand — this preserves the SKILL.md context budget.

**File cap:** each `examples/*.md` file must be ≤120 lines. `scripts/validate.py` (`check_examples()`) enforces this. Examples that grow beyond 120 lines should be split by sub-topic or trimmed.

**Multi-component examples use multiple fenced blocks, not one mega-blob.** When a pattern involves several files (Model + View + Controller), use a separate fence per file, each prefixed with a `// file: path/to/file.ext` (or `# file:` for Python) comment header. Anti-pattern: a single 200-line fence containing all three components.

## Adding an interactive command with interrogation mode

Interactive commands (those that delegate to a subagent to produce an artifact) support `standard` vs `grill-me` interrogation mode via a shared prelude convention. When adding such a command:

1. Copy the content of `commands/shared/interrogation-prelude.md` verbatim into the new command file, positioned **after** any ticket-context prelude and **before** the subagent delegation or skill activation instruction.
2. Add the command name (without `.md`) to `_E312_COMMANDS` in `tests/test_validate.py`. The `TestInterrogationPreludeUniformity` class enforces byte-identical parity between the shared file and every command in the list.
3. Append ` [--grill | --standard]` to the command's `argument-hint` frontmatter field.
4. Add a `workflow-grill` trigger row note to the command's entry in `docs/catalog.md`.

**Orchestrator-only rule:** the mode gate (`AskUserQuestion`) and the `swe-workbench:workflow-grill` loop run in the command body (orchestrator). Never embed them in a shared subagent — it would bleed the mode prompt into flows that reuse the same agent (e.g. `product-manager` is shared with `/swe-workbench:report-issue`; `senior-engineer` is consulted by `/swe-workbench:implement`).

**Member visibility ordering: `public > protected > private`.** Public API surface reads first so consumers can scan the contract without scrolling past implementation details. Per-language translation:

| Language | Ordering rule |
|----------|--------------|
| Java / TypeScript / Swift | Explicit modifiers in order: `public` → `protected` → `private` |
| Kotlin | `public` → `internal` → `protected` → `private` (defaults to `public`, so mark what is *restricted*) |
| Go | Exported (Capitalized) declarations before unexported (lowercase) |
| Python | Convention-only: public (no underscore) → `_protected` → `__private` |
| Rust | `pub` → `pub(crate)` → private (no modifier) |
| SQL | Not applicable |
