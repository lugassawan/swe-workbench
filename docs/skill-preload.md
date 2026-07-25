# Skill preload via frontmatter

Some agents open with a step that always fires — "load heuristics before reading the diff" is not conditional on what the diff contains. For those, invoking the skill via the `Skill` tool costs a full tool round-trip that buys nothing: the outcome was never in doubt. Claude Code's agent `skills:` frontmatter lets the harness inject that skill's content at dispatch time instead, before the agent's first turn.

This started narrow (issue #558: three agents, one always-fire skill each) and was later extended per-agent, assessed one catalog at a time rather than by blanket rule (issue #562): most agents now preload some or all of their `## Principle consultation` catalog. The live, authoritative mapping of which agent preloads which skill is each agent's own `skills:` frontmatter — `tests/test_skill_preload.py` discovers it dynamically rather than duplicating it in a hand-maintained table here, so it can't drift out of sync.

## How much of a catalog gets preloaded

Assessed per agent, not by a size rule:

- **Single-skill agents** (e.g. `test-writer` originally) — the one always-fire skill.
- **Small catalogs** (e.g. `auditor`'s 7) — the whole catalog, when the agent's own default behavior touches most or all of it on every dispatch.
- **Large catalogs** (`senior-engineer`: 14 skills; `architect`: 12; `migrator`: 8) — assessed and moved in full (or near-full), on the judgment that the round-trip savings across common cases outweigh the fixed preload cost for these specific agents.
- **Partial catalogs** — an agent can preload most of its catalog while deliberately leaving a few entries conditional. `senior-engineer` preloads 11 of its 14 skills; `principle-cost-awareness`, `principle-release-engineering`, and `principle-postmortem` stay as on-demand body-only bullets, judged to be rare enough for that agent not to justify preloading. `reviewer` preloads 14 of its 15 skills; `principle-i18n` stays conditional since not every review is i18n-related. Both agents keep a short framing sentence above their remaining conditional bullets so the agent's own prompt still instructs it to reach for them when relevant.

`security-auditor` was excluded from the original #558 scope (its `principle-security` use was judged conditional-by-design) but was later folded in — that exclusion was reassessed, not overridden by a blanket rule.

## Body bullets are no longer required

Earlier iterations of this mechanism required every preloaded skill to keep a backticked `` `swe-workbench:<id>` `` body mention alongside its frontmatter entry, reasoning that duplicating it gave a fallback path if a preload ever silently failed. That retention requirement has since been dropped as unnecessary duplication at this scale: `check_unwired_principle_skills` (in `scripts/validate.py`) now recognizes an agent's `skills:` frontmatter entry as wiring in its own right, not just a backticked body reference. `check_preloaded_skills` no longer checks for a body mention at all.

Practically: an agent can preload a skill via frontmatter with **no** corresponding body text, and that's a valid, fully-wired state. A body mention is still fine to keep where it adds useful "what this skill covers" documentation (many agents do), but it's no longer load-bearing for validation.

## The silent-failure trap

Namespacing is not cosmetic. `swe-workbench:principle-code-review` in `skills:` frontmatter loads the skill's content at dispatch. The bare form, `principle-code-review`, silently no-ops — the agent starts with nothing preloaded and no error.

The trap: the harness's `[Agent: X] Preloaded skill '…'` debug line prints **identically** whether the namespaced or bare form was used. Seeing that line in a debug log is not evidence of successful injection — it fires regardless of whether the skill actually loaded. This was confirmed by direct spike during issue #558's investigation, and it's why `check_preloaded_skills` hard-fails any non-namespaced entry rather than warning.

## Manual verification runbook

There is no automated dispatch harness in this repo (no `claude -p` / `--debug-file` / API-credential plumbing exists across the test suite), so confirming a preload actually injected requires one manual check per changed agent:

1. Dispatch the agent (e.g. `swe-workbench:reviewer` via the `Agent` tool).
2. Ask it to report any `preload-canary` HTML comment token present in its context, verbatim.
3. Compare the reported token against the target skill's canary — e.g. `SWB-PRELOAD-PRINCIPLE-CODE-REVIEW` for `principle-code-review`.

Seeing the exact token back confirms real injection. Silence, a different token, or a refusal to find one means the preload did not take — recheck the frontmatter's namespacing before trusting the debug log.

**Caveat recorded during issue #558's own PR:** dispatching `swe-workbench:reviewer` via the in-session `Agent` tool and asking it to report the canary returned no token — and a follow-up check for skill-body-unique phrases (`Five-Axis Review Lens`, `Confidence-Based Filtering`, present only inside `principle-code-review`'s body) also came back negative. That reads like a contradiction of issue #558's Spike 1, which recorded the namespaced form working — but Spike 1 dispatched via a separate OS process (`claude -p ... --debug-file`), not the in-session `Agent` tool used here. Those are plausibly two different dispatch code paths, and there's no evidence the in-session `Agent` tool honors agent-level `skills:` frontmatter the same way an out-of-process `claude -p` invocation does. Treat "the `Agent` tool shows no injection" as inconclusive on this mechanism's real-world behavior, not as proof it's broken; if you need a definitive answer, re-run Spike 1's exact method (`claude -p ... --debug-file`, checking the *response content* for injected skill text, not just the debug log line) rather than the in-session `Agent` tool.

Each preloaded skill carries its own canary comment immediately after the closing frontmatter `---`, e.g.:

```markdown
---
name: principle-code-review
description: …
---
<!-- preload-canary: SWB-PRELOAD-PRINCIPLE-CODE-REVIEW -->
```

The rule is mechanical: `SWB-PRELOAD-` followed by the skill id, uppercased.

## Deliberately not preloaded

- **`language-*` skills, in general** — which language applies is unknown until the diff is read; there's nothing to preload before that. One deliberate exception: `accessibility-auditor` preloads `swe-workbench:language-typescript`, since that agent is scoped specifically to frontend/TSX review — unlike general-purpose agents, the applicable language isn't actually in doubt for it.
- **Individual catalog entries an agent's own assessment left conditional** — e.g. `senior-engineer`'s `principle-cost-awareness`, `principle-release-engineering`, and `principle-postmortem`, and `reviewer`'s `principle-i18n` (see above). Not a blanket exclusion — just the outcome of that agent's specific assessment.
- **A live-dispatch CI canary** — acceptance criterion #2 from issue #558 called for a CI-enforced dispatch check. No agent-dispatch harness exists in this repo, and building one would cost more than the frontmatter changes it would guard. The manual runbook above is the intentionally-downgraded substitute.
