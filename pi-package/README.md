# SWE Workbench for pi

This directory is a pi package port of the Claude Code `swe-workbench` plugin in the repository root.

## Resource mapping

- `prompts/*.md` are pi-specific ports generated from `../commands/*.md`. The originals contain Claude-specific subagent/Skill references, so the ported prompt files add a pi mapping note instead of symlinking.
- The publishable root package manifest loads `../skills` directly. In a source checkout, `skills/*` symlinks may also exist here for local `pi -e ./pi-package` experiments, but the npm/pi.dev package is intended to be installed from the repository/package root.
- `agent-skills/*/SKILL.md` are pi-specific adapter files generated from `../agents/*.md`. Claude Code agents are not native pi resources, and their frontmatter contains Claude-specific `model` and `tools` fields, so these are ported rather than symlinked.
- `extensions/index.ts` ports the Claude hook behavior that is meaningful in pi:
  - blocks dangerous bash commands similar to `hooks/bash_guard.sh`;
  - blocks hardcoded secrets on write/edit similar to `hooks/secret_guard.py`;
  - emits language-skill hints when read/edit/write touches a known source file extension;
  - marks the package as loaded in pi status.

Claude-specific hook events such as `SubagentStop` skill telemetry and `SessionStart` compaction-resume injection do not have exact pi equivalents in this package. Their source files remain untouched in the root Claude plugin.

## Regenerating adapters

The files under `prompts/` and `agent-skills/agent-*` are ports, not authoritative source. If the root Claude commands or agents change, regenerate these adapters by applying the same simple transformation documented above: keep frontmatter/instructions, add the pi port note, and map Claude subagent invocations to `agent-*` skills.

## Try locally

Use the repository/package root so pi reads the publishable root `package.json` manifest:

```bash
pi -e .
```

Or install as a local package:

```bash
pi install .
```
