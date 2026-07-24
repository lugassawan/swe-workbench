# Design — Convert principles & languages from skills to plain-`.md` rules (supersedes #545)

## Status

**This supersedes issue #545.** #545's acceptance criteria explicitly required the
`swe-workbench:principle-*` / `language-*` **skill-invocation surface to survive** ("directory
reorganization, not a rename"). This design deliberately **removes** that surface. #545 was
re-scoped in place to describe *this* redesign; the delivering PR closes #545 as re-scoped.

## Context

The 39 `principle-*` (27) + `language-*` (12) directories under `skills/` are conceptually **rules**
(persistent guidelines the agent follows), not **skills** (procedures the agent runs). The maintainer
wants them modeled as rules: authored in rules style, with a **catalog surfaced at session start** and
**bodies loaded lazily**.

Hard platform constraint (docs-confirmed): **Claude Code plugins cannot ship the native `.claude/rules/`
primitive** — there is no manifest `rules` key, and `paths:` frontmatter is inert in a plugin. So this
design **emulates** the rules model with plugin-native parts: plain `.md` bodies + a hook-injected
catalog + on-demand `cat`.

**Accepted tradeoff (eyes open, per senior-engineer consult):** this drops a public, documented,
tested invocation surface and hand-rolls a lazy-load the Skill tool already provides, in exchange for
the rules *conceptual model* the maintainer wants. The maintainer chose this after a full consult that
recommended against it.

## Resolved decisions

- **Bodies:** plain `.md` files (no `SKILL.md`, no skill registration) under a top-level `rules/` dir.
- **NOT registered as skills:** no `"skills": "./rules"` in `plugin.json`. They are files, not skills.
- **Agent access:** on demand via `cat "$CLAUDE_PLUGIN_ROOT/rules/<name>.md"` (Bash). **Runtime
  correction (found during implementation):** `inject_plugin_root.sh` only rewrites a Bash command
  whose *own triggering process* already has `$CLAUDE_PLUGIN_ROOT` set — true for the main/orchestrator
  session's own Bash calls (proven, and what `commands/{capture,doctor,report-issue}.md` actually rely
  on) but empirically **not** true for a dispatched subagent's own Bash calls (confirmed via two
  independent subagent dispatches, both saw an empty var). `agents/product-manager.md`'s pre-existing
  `${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}` hedge was itself evidence of this gap, and
  its fallback is wrong for a real install anyway (resolves to the *end user's* repo root, not the
  plugin's). Fixed with a new `SubagentStart` hook — see "Agent access, corrected" below.

  **Agent access, corrected:** `hooks/inject_plugin_root_subagent.sh` (`SubagentStart`, matcher
  `^swe-workbench:.*$`) fires at dispatch time, in the orchestrator's own environment (where the var
  *is* reliably set), and injects the already-resolved literal path via `additionalContext` with an
  instruction to substitute it wherever the agent's own prompt says `$CLAUDE_PLUGIN_ROOT`, rather than
  relying on shell expansion inside the subagent's own Bash calls. This required no changes to the 21
  agent files themselves — they still read `cat "$CLAUDE_PLUGIN_ROOT/rules/<name>.md"`; the model
  substitutes the literal path from its SubagentStart context when issuing the actual Bash command.
  **Residual risk (two, not one):**
  1. Whether `SubagentStart`'s own hook process reliably inherits `$CLAUDE_PLUGIN_ROOT` is itself
     undocumented — if it doesn't, this hook silently emits nothing (fail-open) and the subagent's
     bare `$CLAUDE_PLUGIN_ROOT` reference fails loud (empty path, file-not-found) — a discoverable
     failure in testing/review, not a silently-masked one.
  2. The matcher `^swe-workbench:.*$` assumes `SubagentStart`'s `agent_type` field is the
     plugin-scoped identifier (`swe-workbench:reviewer`). Docs research (two independent rounds)
     found this documented explicitly for both `SubagentStart` and `PreToolUse`'s `agent_type` field
     — but a *pre-existing, unrelated* hook in this same repo, `hooks/skill_usage_record.sh`
     (`PreToolUse:Skill`), validates its own `agent_type` as a **bare** identifier
     (`^[A-Za-z0-9_-]+$`, no colon) and looks it up as `agents/$agent_type.md`. That hook predates
     this PR and wasn't touched by it, so either it's carrying a latent bug the plugin-prefixed
     format would have caught, or the two hook events genuinely populate `agent_type` differently. If
     the bare-name reading is actually correct for `SubagentStart` too, this hook's matcher would
     never fire and it would need to change to a bare-name pattern instead. Verify both risks live in
     a real install before relying on this in production.
- **Catalog:** evolved the existing `agents/shared/{principles,languages}.md` into the catalog — each
  entry is `name · when-it-applies · rules/<name>.md`. Single source; no third copy.
- **Two catalog delivery paths:** (a) **main thread** — a SessionStart hook (`hooks/inject_catalog.sh`)
  injects the catalog as `additionalContext`; (b) **subagents** — keep the embedded
  `@./shared/{principles,languages}.md` include (subagents don't receive SessionStart context).
- **Path-scoping:** `paths:` is inert; repointed `hooks/skill_autoload_hint.sh`'s ext→name map to emit
  "consult rule X" hints. Principles stay catalog+judgment (no equivalent auto-hint mechanism — there
  was never a description-drift/BM25 signal for principles even under the skill model).
- **Retirement:** abrupt drop in one release (0.x permits it). Deleted the 39 skills, updated all
  internal refs, announced the breaking change in the PR/release notes.
- **Validation/BM25:** ported structural + catalog-sync checks to the rule model; retired
  `triggers.txt` + the nightly BM25 harness for the converted 39 (they no longer autoload via the
  skill harness).
- **Always-on cost:** catalog ≈ 6.5 KB ≈ ~1,600 tokens into the main thread every session — accepted.

## Architecture

```
rules/                         # plain .md, one topic per file (NOT skills)
  principle-tdd.md
  language-python.md
  ...
  <name>/examples/*.md         # optional, for rules with worked per-language examples
agents/shared/
  principles.md   languages.md # catalog: name · when-applies · rules/<name>.md
hooks/
  inject_catalog.sh              # SessionStart hook → injects catalog as additionalContext (main thread)
  inject_plugin_root_subagent.sh # SubagentStart hook → hands dispatched swe-workbench:* agents the
                                  # resolved $CLAUDE_PLUGIN_ROOT as a literal path (see runtime
                                  # correction above — bare $CLAUDE_PLUGIN_ROOT doesn't resolve in a
                                  # subagent's own Bash calls)
  skill_autoload_hint.sh         # repointed: ext→"consult rule X" instead of "invoke skill X"
scripts/validate.py            # rule-model checks replace skill-model checks for these 39
```

**Data flow.** Main thread: SessionStart → catalog injected → orchestrator knows the rule set and
`cat`s a body when relevant. Subagent (e.g. reviewer): embedded catalog include → agent decides a rule
applies → `cat "$CLAUDE_PLUGIN_ROOT/rules/principle-code-review.md"` → body enters that agent's context.

## Implementation — grouped by commit-taxonomy axis

**Group 1 — Rules corpus (Infrastructure).** Converted 39 `skills/{principle,language}-*/SKILL.md` →
`rules/<name>.md` (stripped skill frontmatter to rules-style: `# Title` + `> **Applies:**` note +
body). Dropped each `triggers.txt`. Preserved the 8 rules with `examples/` subdirectories
(`principle-clean-architecture`, `principle-concurrency`, `principle-ddd`, `principle-design-patterns`,
`principle-error-handling`, `principle-performance`, `principle-resiliency`, `principle-solid`) as
`rules/<name>/examples/*.md`, rewriting their "See `examples/`" pointers to
"See `rules/<name>/examples/`". Git-detected renames preserve history. No `plugin.json` change.

**Group 2 — Catalog + delivery (Core logic).**
- Rewrote `agents/shared/{principles,languages}.md` entries to `name · when-applies · rules/<name>.md`.
- New `hooks/inject_catalog.sh` (SessionStart, matchers `startup|resume|compact`) emitting the catalog as
  `additionalContext`; wired into `hooks/hooks.json` alongside `workflow_resume_hint.sh`.
- Repointed `hooks/skill_autoload_hint.sh` ext→name map to "consult rule `<name>`" phrasing.

**Group 3 — Consumer rewrite (Wiring).** Rewrote the 22 agents + `commands/{implement,extend}.md` +
5 cross-referencing workflow skills: replaced every `Skill`-based `swe-workbench:principle-*` /
`language-*` invocation with a `cat "$CLAUDE_PLUGIN_ROOT/rules/<name>.md"` instruction. Kept the
`@./shared` catalog includes.

**Group 4 — Validation + tests (Tests).**
- `scripts/validate.py`: removed the 39 from skill-model checks; added rule-model checks —
  `check_catalog_completeness()` now sources `principles.md`/`languages.md` from `rules/` (new bullet
  format, with an arrow-target mismatch check) while `workflows.md` stays skill-sourced;
  `check_unwired_principle_rules()` (renamed from `check_unwired_principle_skills()`) requires every
  `rules/principle-*.md` be referenced by ≥1 agent (`language-*` stays exempt — wired dynamically, not
  enumerated); new `check_no_stale_principle_language_skill_refs()` fails on any remaining
  `swe-workbench:principle-*`/`language-*` reference anywhere in `agents/`, `commands/`, `skills/`;
  `check_examples()` repointed to `rules/*/examples/**/*.md`. Retired `triggers.txt` enforcement + BM25
  for these 39 (they simply fall out of `skills/*/triggers.txt` globs — no explicit exclusion needed).
- `tests/`: rewrote skill-model assertions (`helpers.py` gained a `rules=` fixture param;
  `test_agent_language_catalog.py`, `test_skill_triggers.py`, `test_validate.py`, and ~10 other files
  updated to the rule model).

## Verification (end-to-end)

1. `bash scripts/validate.sh` — green (rule-model checks; zero dangling skill refs).
2. `pytest tests/ -v` — all pass.
3. **Empirical:** confirmed the SessionStart hook (`inject_catalog.sh`) injects the catalog correctly
   (direct hook invocation, ~7.6 KB output). Confirmed `$CLAUDE_PLUGIN_ROOT` resolves in the
   main/orchestrator session's own Bash calls. Confirmed (via two independent subagent dispatches)
   that it does **not** resolve in a subagent's own Bash calls, which led to the
   `inject_plugin_root_subagent.sh` fix above — **not yet verified live** (requires installing this
   branch in a real session; see the residual-risk note above).
4. `grep -rE "swe-workbench:(principle|language)-" agents/ commands/ skills/` returns zero
   (surface fully retired) — confirmed.
