# Principles & languages as rules

## Overview

The 39 `principle-*` (27) and `language-*` (12) topics under the plugin are modeled as **rules** —
persistent guidelines the agent follows — rather than **skills** — procedures the agent runs. They
live as plain `.md` files under a top-level `rules/` directory: no `SKILL.md`, no `plugin.json`
registration, no `Skill`-tool invocation, no `triggers.txt`/BM25 auto-trigger harness. A body loads on
demand via `cat "$CLAUDE_PLUGIN_ROOT/rules/<name>.md"`.

This is a conceptual shift, not a directory move: it changes how these 39 topics are discovered and
loaded, and it removes the `swe-workbench:principle-*`/`language-*` `Skill`-invocation surface
entirely — a breaking change to a previously documented, tested interface. The tradeoff is deliberate:
this design forgoes the lazy-loading and auto-discovery the `Skill` tool already provides, in exchange
for a rules model that separates "knowledge the agent follows" from "procedures the agent runs".

## Platform constraint

Claude Code plugins cannot ship the native `.claude/rules/` primitive — there is no manifest `rules`
key, and `paths:` frontmatter is inert in a plugin context. This design emulates the rules model with
plugin-native parts instead: plain `.md` bodies, a hook-injected catalog, and on-demand loading via
`cat`.

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
                                  # resolved $CLAUDE_PLUGIN_ROOT as a literal path (see "Loading a rule
                                  # body from a subagent" below)
  skill_autoload_hint.sh         # ext→"consult rule X" hints for language-* rules
scripts/validate.py            # rule-model checks for these 39 (catalog sync, wiring, stale refs)
```

**Data flow.** Main thread: a `SessionStart` hook injects the catalog as `additionalContext`, so the
orchestrator knows the rule set and `cat`s a body when relevant. Subagent (e.g. `reviewer`): the
catalog is embedded via the agent's own `@./shared/{principles,languages}.md` include; the agent
decides a rule applies and runs `cat "$CLAUDE_PLUGIN_ROOT/rules/principle-code-review.md"`.

## Catalog

`agents/shared/{principles,languages}.md` is the single source of truth — a catalog entry per rule,
`name · when-it-applies · rules/<name>.md`. It's delivered two ways: the main thread gets it via the
`SessionStart` hook; subagents get it via the existing `@./shared/{principles,languages}.md` include,
since subagents don't receive `SessionStart` context.

`language-*` rules keep an auto-hint: `hooks/skill_autoload_hint.sh` maps file extensions to rule
names and nudges "consult rule `<name>`" when a matching file is touched. `principle-*` rules have no
equivalent signal — there was never a description-drift/BM25 mechanism for principles even under the
skill model — so they're catalog-plus-judgment: the agent decides relevance from the injected catalog,
not from a trigger match.

## Retirement of the skill surface

The conversion is a one-release, atomic cutover: all 39 `skills/{principle,language}-*/SKILL.md` +
`triggers.txt` pairs were replaced by `rules/<name>.md`, every internal consumer (22 agents,
`commands/{implement,extend}.md`, 5 cross-referencing workflow skills) was rewritten from
`Skill`-invocation to `cat`-loading, and `scripts/validate.py` gained a zero-tolerance check
(`check_no_stale_principle_language_skill_refs`) that fails on any remaining
`swe-workbench:principle-*`/`language-*` reference. The nightly BM25 trigger harness
(`tests/test_skill_triggers.py`) and `triggers.txt` enforcement no longer apply to these 39 — they
simply fall out of the `skills/*/triggers.txt` glob.

The 8 rules that had per-language worked examples (`principle-clean-architecture`,
`principle-concurrency`, `principle-ddd`, `principle-design-patterns`, `principle-error-handling`,
`principle-performance`, `principle-resiliency`, `principle-solid`) keep them at
`rules/<name>/examples/*.md`, loaded on demand — never auto-loaded — same as under the skill model.

## Loading a rule body from a subagent

`$CLAUDE_PLUGIN_ROOT` resolves reliably in the main/orchestrator session's own Bash calls (the
pre-existing `hooks/inject_plugin_root.sh`, a `PreToolUse:Bash` hook, handles that case), but **not**
inside a dispatched subagent's own Bash calls — confirmed empirically across independent subagent
dispatches, both of which saw an empty `$CLAUDE_PLUGIN_ROOT`. The variable is present in a hook
script's own process environment when the *triggering* call is the main session's; it is not when the
trigger is a subagent's tool call.

`hooks/inject_plugin_root_subagent.sh` (`SubagentStart`, matcher `^swe-workbench:.*$`) closes this
gap: it fires at dispatch time, in the orchestrator's own environment where the variable *is*
reliably set, and injects the already-resolved literal path via `additionalContext` with an
instruction to substitute it wherever the agent's own prompt says `$CLAUDE_PLUGIN_ROOT`. No agent file
needed to change — they still read `cat "$CLAUDE_PLUGIN_ROOT/rules/<name>.md"`; the model substitutes
the literal path it received at dispatch when it issues the actual Bash command.

**Known limitations, not yet verified against a live install:**

1. Whether `SubagentStart`'s own hook process reliably inherits `$CLAUDE_PLUGIN_ROOT` is undocumented.
   If it doesn't, the hook fails open (emits nothing) and the subagent's bare `$CLAUDE_PLUGIN_ROOT`
   reference fails loud — an empty path, file-not-found — which is discoverable in testing, not a
   silently masked failure.
2. The matcher assumes `SubagentStart`'s `agent_type` field carries the plugin-scoped identifier
   (`swe-workbench:reviewer`). Documentation supports this for both `SubagentStart` and `PreToolUse`,
   but a pre-existing, unrelated hook in this repo (`hooks/skill_usage_record.sh`, `PreToolUse:Skill`)
   validates its own `agent_type` as a bare identifier (no colon) and looks it up as
   `agents/$agent_type.md`. That hook predates this design and wasn't changed by it; either it carries
   a latent bug the plugin-scoped format would have caught, or the two hook events populate
   `agent_type` differently. If the bare-name reading turns out to be correct for `SubagentStart` too,
   this hook's matcher needs to change to a bare-name pattern.

Both risks fail safely (loud, not silent) if the assumption is wrong. Verify live before relying on
this in production.

## Cost

The catalog adds roughly 6.5 KB (~1,600 tokens) to the main thread on every session start via
`inject_catalog.sh`. Accepted as the cost of the catalog-visibility model.

## Relationship to issue #545

This design supersedes #545 as originally filed. #545's acceptance criteria required the
`swe-workbench:principle-*`/`language-*` Skill-invocation surface to survive ("directory
reorganization, not a rename"); this design removes it. #545 was re-scoped in place to describe this
redesign, and the delivering PR closes it as re-scoped.

## Verification

1. `bash scripts/validate.sh` — rule-model checks pass; zero dangling skill refs.
2. `pytest tests/ -v` — full suite passes.
3. `hooks/inject_catalog.sh` confirmed via direct invocation to inject the catalog correctly
   (~7.6 KB output). `$CLAUDE_PLUGIN_ROOT` confirmed to resolve in the main/orchestrator session's own
   Bash calls and confirmed *not* to resolve in a subagent's own Bash calls — see "Loading a rule body
   from a subagent" above.
4. `grep -rE "swe-workbench:(principle|language)-" agents/ commands/ skills/` returns zero hits.
