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
- `hooks/hooks.json` — JSON well-formedness and structural shape.
- `skills/*/SKILL.md` — flat layout (no nesting), required frontmatter (`name`, `description`), `name` matches directory name, ≤150-line cap (≤300 for skills with `orchestrator: true`).
- `agents/*.md` — required frontmatter (`name`, `description`).
- `commands/*.md` — required frontmatter (`description`).
- `skills/*/templates/*.md` — every `[[detect:KEY]]` marker is documented in the adjacent `SKILL.md`'s `## Project Detection` section.
- `skills/*/triggers.txt` — every skill must have a sibling `triggers.txt` with ≥2 non-empty non-comment lines (each ≤200 chars).
- `skills/*/examples/**/*.md` — companion example files must be ≤120 lines each. See `docs/extending.md` for the full `examples/` convention (multi-fence `// file:` header rule, visibility ordering).
- Dependency-flow graph (`check_no_cycles`) — action-cued `` `swe-workbench:<id>` `` activations must not form cycles across commands, skills, and agents. See `docs/extending.md` (`## Dependency flow`) for the allowed layering rules that this check enforces.

The same checks run in CI on every PR (`validate-plugin-files` job in `.github/workflows/pr.yml`).

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

**Skill catalog**: The catalog is split across three slice files under `agents/shared/`: `principles.md`, `languages.md`, and `workflows.md`. When you add a new skill, add a corresponding entry in the appropriate slice (format: `- \`swe-workbench:<name>\` — <one-line description>`). The slice is determined by the skill-name prefix: `principle-*` → `principles.md`; `language-*` → `languages.md`; `workflow-*` and `ticket-context` → `workflows.md`; any other prefix defaults to `principles.md`. The validator's `check_catalog_completeness()` enforces that each slice exactly matches the on-disk skills in its prefix group, and that every agent file includes at least one slice via `@./shared/principles.md`, `@./shared/languages.md`, or `@./shared/workflows.md`. Code-touching agents that include `@./shared/principles.md` must also include `@./shared/languages.md` so language-specific skills are always in scope. If the new agent never touches source code, add its stem to the `_NON_CODE_AGENTS` set at the top of `scripts/validate.py` to suppress this check. See `docs/extending.md` for the full recipe.

## Cutting a release

Run the release script from a clean `main`:

```sh
./scripts/release.sh patch   # or minor / major
```

It bumps both manifests, opens a PR, waits for CI to pass, auto-merges, then pushes a `v*.*.*` tag. The tag push triggers `.github/workflows/release.yml`, which validates the manifests and publishes a GitHub Release with auto-generated notes.

## Adding a new interactive command

When creating a new interactive command that supports interrogation mode (i.e. one that delegates to a subagent to produce an artifact), inline the canonical interrogation prelude verbatim from `commands/shared/interrogation-prelude.md`:

1. Copy the file content exactly into the new command, positioned after any ticket-context prelude and before the subagent delegation or skill activation instruction.
2. Add the command name (without `.md`) to `_E312_COMMANDS` in `tests/test_validate.py` — the `TestInterrogationPreludeUniformity` class will then enforce that the prelude stays in sync.
3. Append ` [--grill | --standard]` to the command's `argument-hint` frontmatter field.
4. Add the command name to the `argument-hint` note in `docs/catalog.md`.

**Important:** the mode gate (`AskUserQuestion`) and the grill loop (`swe-workbench:workflow-grill`) run in the **orchestrator** (command body), never in a shared subagent. Embedding it in a shared subagent (e.g. `product-manager`, `senior-engineer`) would leak the mode gate into other flows that reuse the same agent.

## `.githooks/` vs `hooks/hooks.json`

These two directories share the same depth but serve different runtimes:

| Path | Purpose |
|---|---|
| `.githooks/` | Git hooks (`commit-msg`, `pre-commit`, `pre-push`) — invoked by git. |
| `hooks/hooks.json` | Claude Code plugin runtime hooks — invoked by the Claude Code plugin system. |
