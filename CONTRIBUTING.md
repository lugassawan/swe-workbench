# Contributing

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Setup

After cloning, run the setup script once:

```sh
./scripts/setup.sh
```

This installs per-file symlinks in `.git/hooks/` pointing at `.githooks/`. After a successful run, no `core.hooksPath` config is set — the default git hook location is used, which is resistant to tools that reset that key.

If you have pre-existing hooks in `.git/hooks/` or a non-default repo-local `core.hooksPath`, setup.sh will refuse to overwrite them and print a conflict list. Re-run with `--force` to acknowledge and overwrite:

```sh
./scripts/setup.sh --force
```

> **Note:** If a new hook is added to `.githooks/`, re-run `./scripts/setup.sh` to install its symlink. Re-running on an already-configured repo is safe — no warnings are emitted to stderr.

## Branch naming

The `pre-commit` hook blocks direct commits to `main` and `master`. Always work on a feature branch:

```sh
git checkout -b feat/<topic>
```

## Commit message format

The `commit-msg` hook enforces a `[type] Subject` prefix on every commit:

```
[feat] Add Python language skill
[fix] Resolve trigger keyword collision in DDD skill
[docs] Clarify F.I.R.S.T. principle in TDD skill
[chore]: Bump actions/setup-python from 5 to 6
```

Allowed types: `feat`, `fix`, `refactor`, `test`, `ci`, `docs`, `perf`, `chore`, `polish`, `breaking`.

Merge commits and reverts are exempt. The same pattern is validated by CI (see `.github/workflows/pr.yml`).

## Pull requests

Use the PR template (`.github/PULL_REQUEST_TEMPLATE.md`). It requires:

- A summary of what changed and why.
- A test plan with checkboxes.
- An issue reference: `Closes #<number>`, `Fixes #<number>`, or `Resolves #<number>`. For ad-hoc changes without an issue, put a standalone `N/A` line (with an optional reason) — `Closes N/A` and `Closes #N/A` are malformed and will fail CI.
- PR title must match the same `[type] Subject` format as commit messages.

## CI mirror

`.github/workflows/pr.yml` runs the same commit-format and issue-reference checks on every PR. Skipping local setup does not skip CI — it just shifts the failure to after you push.

## Validator

Run the plugin self-validator locally before pushing:

```sh
bash scripts/validate.sh
```

It checks:

- `.claude-plugin/plugin.json` — JSON well-formedness, required fields (`name`, `version`, `description`).
- `.claude-plugin/marketplace.json` — JSON well-formedness, `plugins[0].name` and `plugins[0].version` match `plugin.json`.
- `package.json` (root) — version matches `plugin.json`, `private: true`, `pi.extensions` present, `pi.skills`/`pi.prompts`/`pi.themes` absent. See "Pi adapter" below.
- `hooks/hooks.json` — JSON well-formedness and structural shape.
- `skills/*/SKILL.md` — flat layout (no nesting), required frontmatter (`name`, `description`), `name` matches directory name, ≤150-line cap (≤300 for skills with `orchestrator: true`). A skill at or under 150 lines that declares `orchestrator: true` must reference at least one other skill or agent — the flag must be earned by composition or by size, not added opportunistically. See `docs/extending.md` (`## Philosophy`).
- `agents/*.md` — required frontmatter (`name`, `description`).
- `commands/*.md` — required frontmatter (`description`).
- `skills/*/templates/*.md` — every `[[detect:KEY]]` marker is documented in the adjacent `SKILL.md`'s `## Project Detection` section.
- `skills/*/triggers.txt` — every skill must have a sibling `triggers.txt` with ≥2 non-empty non-comment lines (each ≤200 chars).
- `skills/*/examples/**/*.md` — companion example files must be ≤120 lines each. See `docs/extending.md` for the full `examples/` convention (multi-fence `// file:` header rule, visibility ordering).
- Dependency-flow graph (`check_no_cycles`) — action-cued `` `swe-workbench:<id>` `` activations must not form cycles across commands, skills, and agents. See `docs/extending.md` (`## Dependency flow`) for the allowed layering rules that this check enforces.
- Bare actionable references (`check_bare_actionable_refs`) — every skill/agent id in any `*.md` file outside `tests/` and outside fenced code must use the namespaced `` `swe-workbench:<id>` `` form, including prose, catalog tables, README enumerations, and a file naming itself; the only opt-out is `<!-- validate: prose-ref -->` on a genuinely non-dispatch line.

The same checks run in CI on every PR (`validate-plugin-files` job in `.github/workflows/pr.yml`). That
job also runs `bash scripts/bump-version.sh --audit`, which fails the PR if the current version string
appears in a file not declared in `.version-bump.json`.

## Testing locally

```sh
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

**Trigger fixtures**: every `skills/<name>/` directory must contain a `triggers.txt` with ≥2 representative prompts that a user would type to invoke the skill. These fixtures are used by the **Skill Auto-Trigger Harness** (`.github/workflows/skill-triggers.yml`), which runs nightly and scores each skill's description against its fixtures using BM25. A skill whose description fails to rank top-1 for its own prompts is flagged as drifted. When adding or editing a skill, keep `triggers.txt` in sync so the prompts still match the description's vocabulary. For documented intentional overlaps between sibling skills, add a group entry to `tests/skill_sibling_sets.txt`.

**Skill directory layout**: Skills must live at `skills/<skill-name>/SKILL.md` — exactly one level deep. Claude Code's auto-discovery does not recurse into nested category subdirectories. Use a hyphenated prefix to preserve categorical grouping while meeting this constraint: `principle-*`, `language-*`, `workflow-*`. The `name:` field in the `SKILL.md` frontmatter must match the directory name exactly.

**Skill catalog**: The catalog is split across three slice files under `shared/agents/`: `principles.md`, `languages.md`, and `workflows.md`. When you add a new skill, add a corresponding entry in the appropriate slice (format: `- \`swe-workbench:<name>\` — <one-line description>`). The slice is determined by the skill-name prefix: `principle-*` → `principles.md`; `language-*` → `languages.md`; `workflow-*` and the `*-context` family (matched by `sid.endswith("-context")`, e.g. `ticket-context`) → `workflows.md`; any other prefix defaults to `principles.md`. <!-- validate: prose-ref --> `check_catalog_completeness()` enforces that each slice exactly matches the on-disk skills in its prefix group.

Agents do not discover this catalog via `@path` includes — `@../shared/agents/principles.md`-style references are never expanded inside an agent body (only in CLAUDE.md memory imports and interactive prompts; see `docs/shared-agent-blocks.md` for the full story). That was a silent no-op in every agent from the day the pattern was introduced until issue #619 fixed it. Instead, every agent carries a `<!-- BEGIN shared/agents/skill-catalog-pointer.md -->` / `<!-- END ... -->` sentinel block — a byte-identical, verbatim copy of `shared/agents/skill-catalog-pointer.md` — which points the agent at the harness's own available-skills listing rather than duplicating the full catalog. Every code-touching agent (any agent whose stem is not in `_NON_CODE_AGENTS`) also carries a `<!-- BEGIN shared/agents/language-skill-required.md -->` sentinel block. `check_catalog_completeness()` checks for these sentinel markers' *presence*; a separate `check_shared_blocks_in_sync()` enforces that every sentinel block's content stays byte-identical to its `shared/agents/*.md` source; and `check_no_inert_at_includes()` permanently bans any `@../shared/` or `@./shared/` reference anywhere in `agents/`, `commands/`, or `skills/`, citing issue #619, so the dead pattern can't quietly reappear. If a new agent never touches source code, add its stem to `_NON_CODE_AGENTS` (unchanged escape hatch). See "Adding a shared agent-body fragment reference" below, and `docs/extending.md`, for the full authoring recipe.

## Cutting a release

Run the release script from a clean `main`:

```sh
./scripts/release.sh patch   # or minor / major
```

It bumps every version field declared in `.version-bump.json` (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, the root `package.json`, and both root-package fields in `package-lock.json`), opens a PR, waits for CI to pass, auto-merges, then pushes a `v*.*.*` tag. The tag push triggers `.github/workflows/release.yml`, which validates the manifests and publishes a GitHub Release with auto-generated notes.

The `bump-version.sh --audit` check described above (see "Validator") is enforced per-PR, so a stray
hardcoded version literal is caught well before the release script ever runs.

## Pi adapter

`pi/extensions/` is a runtime adapter that lets the [Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent) load this plugin's `skills/`, `commands/`, and `agents/` trees unchanged — see `docs/decisions-pi-port.md` and `docs/decisions-task-dispatch.md` for the design rulings behind it. The root `package.json` (there is no `pi/package.json`) is what `pi install git:github.com/lugassawan/swe-workbench` actually reads; Pi's manifest resolution stops at the first `package.json` carrying a `pi` key, and `findPluginRoot()` in `pi/extensions/index.ts` walks up from the extension's own file for `.claude-plugin/plugin.json`, so the publishable unit is the whole plugin tree, not `pi/` alone.

**Setup:**

```sh
npm install
```

**Develop:** edit `pi/extensions/*.ts`. Most of the adapter (`agent-spec.ts`, `model-policy.ts`, `tool-vocab.ts`) is deliberately SDK-free — it imports `@earendil-works/*` only as elided types, never at runtime — so most changes need no `pi` CLI installed to exercise.

**Typecheck:**

```sh
npm run typecheck
```

**Contract tests:**

```sh
pytest tests/test_pi_extension.py tests/test_pi_contract.py -v
```

`test_pi_extension.py` drives the real `pi/extensions/*.ts` under `node --experimental-strip-types` against a stub `ExtensionAPI` — no `pi` CLI or `node_modules` install required, since every `@earendil-works/*` import is type-only and elided by the stripper. `test_pi_contract.py` ratchets the frontmatter/tool-vocabulary boundary between this repo's `agents/*.md`/`commands/*.md` and Pi's own (stricter) YAML parser — a golden-inventory contract, not a schema, per `docs/decisions-ci-validation.md` §1.

**Release:** the root `package.json` and `package-lock.json` version fields are among the fields `scripts/bump-version.sh` keeps in sync (see "Cutting a release" above) — there is no separate manual step, and nothing here is generated, so there is no "regenerate the adapter" step either.

## Adding a new interactive command

When creating a new interactive command that supports interrogation mode (i.e. one that delegates to a subagent to produce an artifact), inline the canonical interrogation prelude verbatim from `shared/commands/interrogation-prelude.md`:

1. Copy the file content exactly into the new command, positioned after any ticket-context prelude and before the subagent delegation or skill activation instruction.
2. Add the command name (without `.md`) to `_E312_COMMANDS` in `tests/test_validate.py` — the `TestInterrogationPreludeUniformity` class will then enforce that the prelude stays in sync.
3. Append ` [--grill | --standard]` to the command's `argument-hint` frontmatter field.
4. Add the command name to the `argument-hint` note in `docs/catalog.md`.
5. Run `pytest tests/test_pi_contract.py -v` — commands are also loaded by the Pi Coding Agent as prompt templates (see "Pi adapter" below); `test_no_pi_argument_substitution_hazard_in_commands` catches a bare `$0`/`$@`/`${N}` in command body text that Pi's own argument-substitution would silently mangle.

**Important:** the mode gate (`AskUserQuestion`) and the grill loop (`swe-workbench:workflow-grill`) run in the **orchestrator** (command body), never in a shared subagent. Embedding it in a shared subagent (e.g. `swe-workbench:product-manager`, `swe-workbench:senior-engineer`) would leak the mode gate into other flows that reuse the same agent.

## Adding a shared agent-body fragment reference

Shared agent-body fragments — the catalog pointer, the language-skill-required list, and the four behavioral-contract fragments (`severity-output-contract.md`, `comment-scan.md`, `external-repo-reading.md`, `lsp.md`) — live under `shared/agents/` and reach a consuming `agents/*.md` file as a sentinel-delimited, byte-identical inline block, never as an `@path` include (see `docs/shared-agent-blocks.md` for why `@path` doesn't work here).

1. Add an **empty** sentinel pair by hand, at the point in the agent file where the fragment belongs:

   ```markdown
   <!-- BEGIN shared/agents/lsp.md -->
   <!-- END shared/agents/lsp.md -->
   ```

2. Run `python3 scripts/sync-shared-blocks.py --write` to fill it with the source file's current content.
3. Run `python3 scripts/sync-shared-blocks.py --check` (or `bash scripts/validate.sh`, which now includes this check) to confirm there's no drift.

**The generator never creates a sentinel pair on its own** — it only fills or verifies pairs a contributor already added by hand. A file with zero sentinel pairs is skipped, not an error. If you edit a `shared/agents/*.md` source file itself, every agent inlining it goes stale until you re-run `--write`; a forgotten sync is caught by `validate.sh`'s `check_shared_blocks_in_sync()`.

## `.githooks/` vs `hooks/hooks.json`

These two directories share the same depth but serve different runtimes:

| Path | Purpose |
|---|---|
| `.githooks/` | Git hooks (`commit-msg`, `pre-commit`, `pre-push`) — invoked by git. |
| `hooks/hooks.json` | Claude Code plugin runtime hooks — invoked by the Claude Code plugin system. |
