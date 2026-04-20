# Extending

## Adding a language skill

To add a new language skill (say, Python):

1. Copy `skills/languages/go/` to `skills/languages/python/`.
2. Rewrite `SKILL.md` frontmatter: `name: python`, and a keyword-rich `description` listing `.py` files, `pyproject.toml`, and common Python terms.
3. Replace the body with the idioms that matter: error handling, typing, packaging, async, testing.
4. Keep it under 150 lines.
5. Commit; users who reinstall the plugin will pick it up.

## Philosophy

Skills are intentionally small — each under 150 lines. A sharp, well-triggered skill teaches Claude the right thing at the right moment. A giant skill burns context on material the current task does not need. If a skill grows past 150 lines, split it.

Orchestrator skills that compose many sub-skills (see the `development` workflow) may exceed 150 lines. When they do, extract conditional content (mode templates, rarely-loaded sub-flows) into companion files inside the skill's directory rather than padding the always-loaded `SKILL.md`.
