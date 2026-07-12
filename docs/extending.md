# Extending

## Adding a language skill

To add a new language skill (say, Ruby or another language not already shipped):

1. Copy `skills/language-go/` to `skills/language-<your-language>/`.
2. Rewrite `SKILL.md` frontmatter: `name: language-<your-language>`, and a keyword-rich `description` listing the language's file types and ecosystem terms.
3. Replace the body with the idioms that matter: error handling, typing, packaging, async, testing.
4. Keep it under 150 lines.
5. Add an entry to `agents/shared/languages.md` (the language slice of the skill catalog) — see CONTRIBUTING.md for the required format and how the validator enforces it.
6. Commit; users who reinstall the plugin will pick it up.

## Adding a context adapter

The `*-context` skills (`ticket-context`, `observability-context`, `comms-context`) are
ports in a ports-and-adapters pattern applied to prose: each skill detects a reference,
fetches via a provider-specific recipe, and emits a shared output block. Adding support
for a new provider — a new tracker, a new observability backend, a new comms tool — is
almost always an **adapter-level change to an existing skill**, not a new skill. Only
propose a new `*-context` skill when the provider represents a genuinely new *kind* of
context (its output doesn't fit any existing skill's envelope).

**To add a provider adapter to an existing `*-context` skill:**

1. Open the skill's `SKILL.md` and add a new `### <Provider>` block under `## Adapters`,
   using the canonical four-field template, **in this order**:

   ```
   ### <Provider>
   - **Trigger:** URL/regex pattern that selects THIS adapter (the discriminator that
     disambiguates it from every other adapter, in this skill and others — see the
     Jira/Linear bare-key tiebreak in `skills/ticket-context/SKILL.md` for a worked
     example of resolving a lexical collision between two providers).
   - **Fetch:** the MCP tool / CLI call sequence. If the plugin ships no integration for
     this provider, say so explicitly and mark the recipe aspirational — it activates
     only if the user has a matching MCP tool connected.
   - **Extract → block fields:** the mapping from the provider's response into the
     skill's *existing* output block fields — never invent a new block shape for one
     provider.
   - **Degrade:** one condition → action row for when the tool/CLI is absent. Never
     fabricate; emit a plain `<skill-id>: <provider> unavailable; proceeding without
     context.` line and stop.
   ```

2. Do not touch the skill's `## Output format` envelope — the header (`## <Kind>
   context: <ref>`), the mandatory `**Source:** <URL>` footer, the PII/secret-strip rule,
   and the ~400-word cap are shared across every adapter in every `*-context` skill. A
   provider that needs a genuinely new field belongs in a new skill, not a bent envelope.
3. Add a trigger prompt for the new provider to the skill's `triggers.txt`
   (≤200 chars), and re-run `pytest tests/test_skill_triggers.py -v` — adding vocabulary
   can thin the BM25 margin (`_SCORE_MARGIN = 0.1`) for other skills' existing prompts via
   IDF drift, not just this one. Fix a thinned margin by tightening the *description* (or
   the drifted trigger prompt), never by weakening another skill's description.
4. Run `bash scripts/validate.sh` — `check_adapter_blocks()` enforces the four-field
   shape (present, in order) on every `skills/*-context/SKILL.md`; `check_catalog_completeness()`
   requires every `*-context` skill (matched by `sid.endswith("-context")`) to have an
   entry in `agents/shared/workflows.md`.
5. Commit; users who reinstall the plugin will pick it up.

**To add a new `*-context` skill (new kind, not a new provider):** copy
`skills/observability-context/` as a template (single-adapter starting point) or
`skills/comms-context/` (multi-adapter starting point), rename to `<kind>-context`, write
its own output envelope, and add its catalog entry to `agents/shared/workflows.md` in the
format `` - `swe-workbench:<kind>-context` — <one-line description> `` (the `*-context`
family routes there regardless of the specific skill name).

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
