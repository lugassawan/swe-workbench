# Contributing

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Setup

After cloning, run the setup script once:

```sh
./scripts/setup.sh
```

This sets `core.hooksPath` to `.githooks/`, activating the two local git hooks described below.

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

**Skill directory layout**: Skills must live at `skills/<skill-name>/SKILL.md` — exactly one level deep. Claude Code's auto-discovery does not recurse into nested category subdirectories. Use a hyphenated prefix to preserve categorical grouping while meeting this constraint: `principle-*`, `language-*`, `workflow-*`. The `name:` field in the `SKILL.md` frontmatter must match the directory name exactly.

## Cutting a release

Run the release script from a clean `main`:

```sh
./scripts/release.sh patch   # or minor / major
```

It bumps both manifests, opens a PR, waits for CI to pass, auto-merges, then pushes a `v*.*.*` tag. The tag push triggers `.github/workflows/release.yml`, which validates the manifests and publishes a GitHub Release with auto-generated notes.

## `.githooks/` vs `hooks/hooks.json`

These two directories share the same depth but serve different runtimes:

| Path | Purpose |
|---|---|
| `.githooks/` | Git hooks (`commit-msg`, `pre-commit`) — invoked by git. |
| `hooks/hooks.json` | Claude Code plugin runtime hooks — invoked by the Claude Code plugin system. |
