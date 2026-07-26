# Skill preload via frontmatter

Some agents open with a step that always fires — "load heuristics before reading the diff" is not conditional on what the diff contains. For those, invoking the skill via the `Skill` tool costs a full tool round-trip that buys nothing: the outcome was never in doubt. Claude Code's agent `skills:` frontmatter lets the harness inject that skill's content at dispatch time instead, before the agent's first turn.

Most agents in this plugin preload some or all of their `## Principle consultation` catalog this way. The live, authoritative mapping of which agent preloads which skill is each agent's own `skills:` frontmatter — `tests/test_skill_preload.py` discovers it dynamically rather than duplicating it in a hand-maintained table here, so it can't drift out of sync.

## How much of a catalog is preloaded

Preload scope varies per agent, not by a fixed size rule:

- **Single-skill agents** (e.g. `test-writer`) — the one always-fire skill.
- **Small catalogs** (e.g. `auditor`'s 7) — the whole catalog, for agents whose default behavior touches most or all of it on every dispatch.
- **Large catalogs** (`senior-engineer`: 14 skills; `architect`: 12; `migrator`: 8) — moved in full or near-full, where the round-trip savings across common cases outweigh the fixed preload cost.
- **Partial catalogs** — an agent can preload most of its catalog while leaving a few entries conditional. `senior-engineer` preloads 11 of its 14 skills; `principle-cost-awareness`, `principle-release-engineering`, and `principle-postmortem` stay as on-demand body-only bullets. `reviewer` preloads 14 of its 15 skills; `principle-i18n` stays conditional since not every review is i18n-related. Both agents keep a short framing sentence above their remaining conditional bullets so the agent's own prompt still instructs it to reach for them when relevant.

## Body bullets are optional

A preloaded skill's frontmatter entry does not need a matching backticked `` `swe-workbench:<id>` `` mention in the agent's body text. `check_unwired_principle_skills` (in `scripts/validate.py`) recognizes an agent's `skills:` frontmatter entry as wiring in its own right; `check_preloaded_skills` does not check for a body mention at all.

An agent can preload a skill via frontmatter with no corresponding body text, and that's a valid, fully-wired state. A body mention is still fine to keep where it adds useful "what this skill covers" documentation (many agents do), but it isn't required for validation.

## The silent-failure trap

Namespacing is not cosmetic. `swe-workbench:principle-code-review` in `skills:` frontmatter loads the skill's content at dispatch. The bare form, `principle-code-review`, silently no-ops — the agent starts with nothing preloaded and no error.

The harness's `[Agent: X] Preloaded skill '…'` debug line prints **identically** whether the namespaced or bare form was used. That line is not evidence of successful injection — it fires regardless of whether the skill actually loaded. This is why `check_preloaded_skills` hard-fails any non-namespaced entry rather than warning.

## Manual verification runbook

There is no automated dispatch harness in this repo (no `claude -p` / `--debug-file` / API-credential plumbing exists across the test suite), so confirming a preload actually injected requires one manual check per changed agent:

1. Dispatch the agent (e.g. `swe-workbench:reviewer` via the `Agent` tool).
2. Ask it to report any `preload-canary` HTML comment token present in its context, verbatim.
3. Compare the reported token against the target skill's canary — e.g. `SWB-PRELOAD-PRINCIPLE-CODE-REVIEW` for `principle-code-review`.

Seeing the exact token back confirms real injection. Silence, a different token, or a refusal to find one means the preload did not take — recheck the frontmatter's namespacing before trusting the debug log.

**Known caveat:** dispatching an agent via the in-session `Agent` tool and asking it to report the canary has been observed to return no token, even for a correctly-namespaced preload — while dispatching the same agent as a separate OS process (`claude -p ... --debug-file`, checking the *response content* rather than the debug log) has been observed to show real injection. These are plausibly two different dispatch code paths, and there's no evidence the in-session `Agent` tool honors agent-level `skills:` frontmatter the same way an out-of-process `claude -p` invocation does. Treat a negative result from the in-session `Agent` tool as inconclusive, not as proof the preload is broken — for a definitive answer, use the out-of-process method instead.

Each preloaded skill carries its own canary comment immediately after the closing frontmatter `---`, e.g.:

```markdown
---
name: principle-code-review
description: …
---
<!-- preload-canary: SWB-PRELOAD-PRINCIPLE-CODE-REVIEW -->
```

The rule is mechanical: `SWB-PRELOAD-` followed by the skill id, uppercased.

## Not preloaded

- **`language-*` skills, in general** — which language applies is unknown until the diff is read; there's nothing to preload before that. One exception: `accessibility-auditor` preloads `swe-workbench:language-typescript`, since that agent is scoped specifically to frontend/TSX review — unlike general-purpose agents, the applicable language isn't actually in doubt for it.
- **Individual catalog entries a given agent leaves conditional** — e.g. `senior-engineer`'s `principle-cost-awareness`, `principle-release-engineering`, and `principle-postmortem`, and `reviewer`'s `principle-i18n` (see above).
- **Live-dispatch CI verification** — no agent-dispatch harness exists in this repo, and building one would cost more than the frontmatter changes it would guard. The manual runbook above is the substitute.
