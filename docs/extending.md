# Extending

## Adding a language skill

To add a new language skill (say, Ruby or another language not already shipped):

1. Copy `skills/language-go/` to `skills/language-<your-language>/`.
2. Rewrite `SKILL.md` frontmatter: `name: language-<your-language>`, and a keyword-rich `description` listing the language's file types and ecosystem terms.
3. Replace the body with the idioms that matter: error handling, typing, packaging, async, testing.
4. Keep it under 150 lines.
5. Add an entry to `agents/shared/skills.md` (the skill catalog) — see CONTRIBUTING.md for the required format and how the validator enforces it.
6. Commit; users who reinstall the plugin will pick it up.

## Philosophy

Skills are intentionally small — each under 150 lines. A sharp, well-triggered skill teaches Claude the right thing at the right moment. A giant skill burns context on material the current task does not need. If a skill grows past 150 lines, split it.

Orchestrator skills that compose many sub-skills (see the `development` workflow) may exceed 150 lines. When they do, extract conditional content (mode templates, rarely-loaded sub-flows) into companion files inside the skill's directory rather than padding the always-loaded `SKILL.md`.
