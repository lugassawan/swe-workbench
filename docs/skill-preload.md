# Skill preload via frontmatter

Some agents open with a step that always fires — "load heuristics before reading the diff" is not conditional on what the diff contains. For those, invoking the skill via the `Skill` tool costs a full tool round-trip that buys nothing: the outcome was never in doubt. Claude Code's agent `skills:` frontmatter lets the harness inject that skill's content at dispatch time instead, before the agent's first turn.

Most agents in this plugin preload some or all of their `## Principle consultation` catalog this way. The live, authoritative mapping of which agent preloads which skill is each agent's own `skills:` frontmatter — `tests/test_skill_preload.py` discovers it dynamically rather than duplicating it in a hand-maintained table here, so it can't drift out of sync.

## How much of a catalog is preloaded

Preload scope varies per agent, not by a fixed size rule:

- **Single-skill agents** (e.g. `swe-workbench:test-writer`) — the one always-fire skill.
- **Small catalogs** (e.g. `swe-workbench:auditor`'s 7) — the whole catalog, for agents whose default behavior touches most or all of it on every dispatch.
- **Large catalogs** (`swe-workbench:senior-engineer`: 14 skills; `swe-workbench:architect`: 12; `swe-workbench:migrator`: 8) — moved in full or near-full, where the round-trip savings across common cases outweigh the fixed preload cost.
- **Partial catalogs** — an agent can preload most of its catalog while leaving a few entries conditional. `swe-workbench:senior-engineer` preloads 11 of its 14 skills; `swe-workbench:principle-cost-awareness`, `swe-workbench:principle-release-engineering`, and `swe-workbench:principle-postmortem` stay as on-demand body-only bullets. `swe-workbench:reviewer` preloads 14 of its 15 skills; `swe-workbench:principle-i18n` stays conditional since not every review is i18n-related. Both agents keep a short framing sentence above their remaining conditional bullets so the agent's own prompt still instructs it to reach for them when relevant.

## Body bullets are optional

A preloaded skill's frontmatter entry does not need a matching backticked `` `swe-workbench:<id>` `` mention in the agent's body text. `check_unwired_principle_skills` (in `scripts/validate.py`) recognizes an agent's `skills:` frontmatter entry as wiring in its own right; `check_preloaded_skills` does not check for a body mention at all.

An agent can preload a skill via frontmatter with no corresponding body text, and that's a valid, fully-wired state. A body mention is still fine to keep where it adds useful "what this skill covers" documentation (many agents do), but it isn't required for validation.

## The silent-failure trap

Namespacing is not cosmetic. `swe-workbench:principle-code-review` in `skills:` frontmatter loads the skill's content at dispatch. The bare form, `principle-code-review`, silently no-ops — the agent starts with nothing preloaded and no error. <!-- validate: prose-ref -->

The harness's `[Agent: X] Preloaded skill '…'` debug line prints **identically** whether the namespaced or bare form was used. That line is not evidence of successful injection — it fires regardless of whether the skill actually loaded. This is why `check_preloaded_skills` hard-fails any non-namespaced entry rather than warning.

## Manual verification runbook

There is no automated dispatch harness in this repo (no `claude -p` / `--debug-file` / API-credential plumbing exists across the test suite), so confirming a preload actually injected requires one manual check per changed agent:

1. Dispatch the agent (e.g. `swe-workbench:reviewer` via the `Agent` tool).
2. Ask it to report any `preload-canary` HTML comment token present in its context, verbatim.
3. Compare the reported token against the target skill's canary — e.g. `SWB-PRELOAD-PRINCIPLE-CODE-REVIEW` for `swe-workbench:principle-code-review`.

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

- **`language-*` skills, in general** — which language applies is unknown until the diff is read; there's nothing to preload before that. One exception: `swe-workbench:accessibility-auditor` preloads `swe-workbench:language-typescript`, since that agent is scoped specifically to frontend/TSX review — unlike general-purpose agents, the applicable language isn't actually in doubt for it.
- **Individual catalog entries a given agent leaves conditional** — e.g. `swe-workbench:senior-engineer`'s `swe-workbench:principle-cost-awareness`, `swe-workbench:principle-release-engineering`, and `swe-workbench:principle-postmortem`, and `swe-workbench:reviewer`'s `swe-workbench:principle-i18n` (see above).
- **Live-dispatch CI verification** — no agent-dispatch harness exists in this repo, and building one would cost more than the frontmatter changes it would guard. The manual runbook above is the substitute.

## On the Pi Coding Agent

There is no `Skill` tool on Pi (`pi/extensions/agent-spec.ts`'s `DROP_TOKENS` explicitly drops
the token `"Skill"` from any tool list it composes), so nothing above about frontmatter-triggered
preloading via a `Skill` tool call applies there. Skills reach a Pi session through three
different, unrelated mechanisms instead:

1. **`resources_discover`'s `skillPaths`** (`pi/extensions/index.ts`) — makes every
   `skills/<name>/SKILL.md` directory reachable to Pi as a skill resource, the same discovery
   Claude Code does natively. This is directory-level discoverability, not per-agent preloading.
2. **The `/skill:<id>` vocabulary legend** — `pi/extensions/tool-vocab.ts`'s `toolVocabSection`
   injects an always-on preamble section (Tier 1, unconditional) telling the model it can invoke
   `swe-workbench:<id>` skills as `/skill:<id>`, with the full on-disk skill id list.
3. **`composeSystemPrompt` inlining** (`pi/extensions/agent-spec.ts`) — when `pi/extensions/subagent.ts`'s
   `task` tool dispatches one of this repo's `agents/*.md` definitions, every skill named in that
   agent's `skills:` frontmatter is composed verbatim into the dispatched child's system prompt,
   the same preload contract this file describes for Claude Code — including the
   `<!-- preload-canary: SWB-PRELOAD-<ID> -->` marker, which is preserved unmodified so the manual
   verification runbook above works identically on both harnesses.

## Demotion decision rule

Preloading a skill is not a one-way door. Demote skill `S` from agent `A` — move it out of
frontmatter, back to conditional — only when **all four** of the following hold:

1. `S` is ≥ 500 tokens of `A`'s dispatch prefix (measured by `scripts/dispatch-ledger.mjs` — see
   the runbook below).
2. `S`'s preload citation (the `SWB-CANARIES-APPLIED` marker, see the runbook below) is cited in
   fewer than 20% of at least 20 sampled dispatches for agent `A`.
3. Ablation (`scripts/preload-probe.mjs ablate`) shows zero lost findings and zero severity
   downgrades on a representative corpus with `S` omitted from `A`'s preload.
4. Cache-read fraction on `A`'s dispatch prefix (`scripts/preload-probe.mjs cache`) is below 0.5.

**A low or zero citation rate under condition 2 must never, by itself, be read as proof the skill
is unused.** The harness where preload demonstrably fires — the Pi Coding Agent, via
`composeSystemPrompt` in `pi/extensions/agent-spec.ts` — has no `SubagentStop` hook to harvest a
citation from at all (`tests/test_pi_contract.py` pins both of Claude Code's telemetry hooks as
explicitly not-applicable on Pi). Meanwhile Claude Code's in-session `Agent` tool, which does have
a `SubagentStop` hook, carries its own already-documented caveat above (see "Known caveat" under
"Manual verification runbook"): it may not honor an agent's `skills:` frontmatter preloading at
all. So a zero citation rate can mean either "genuinely unused" or "collected on a harness where
the signal was never going to fire" — the two are indistinguishable from condition 2 alone. That is
exactly why condition 2 is necessary but never sufficient by itself, and why all four conditions
must hold together before acting on any of them.

The action a passing check authorizes is **demotion, not deletion**: move `S` out of `A`'s
`skills:` frontmatter and into a conditional body bullet, the same pattern
`swe-workbench:senior-engineer` and `swe-workbench:reviewer` already use for the catalog entries
they leave conditional (see "How much of a catalog is preloaded" above).

### Running the instruments

Four scripts back the conditions above. Each one's own `USAGE`/`--help` output and top-of-file
comments are the authoritative reference; this is just a pointer to the invocations a reader would
actually run. `dispatch-ledger.mjs` and `preload-probe.mjs` have no dedicated `--help` handler and
only print a `USAGE` block on an unrecognized argument; `preload-telemetry.py` has a proper
`argparse` `--help`.

- The static ledger (condition 1): `node --experimental-strip-types scripts/dispatch-ledger.mjs --check`
  (and `--write` to regenerate `docs/dispatch-ledger.md`).
- The citation report (condition 2): `python3 scripts/preload-telemetry.py canary`.
- The cache-vs-fresh probe (condition 4) — must be run by a human in their own terminal, not from
  an automated context (`hooks/bash_guard.sh` blocks a nested `pi` session): `node
  --experimental-strip-types scripts/preload-probe.mjs cache --agent <id>`, then `python3
  scripts/preload-telemetry.py cache` to see the accumulated history.
- The ablation harness (condition 3) — also human-run, same constraint: `node
  --experimental-strip-types scripts/preload-probe.mjs ablate --agent <id> --corpus <dir> --omit
  <skill-id>`, then `scripts/preload-probe.mjs ablate --report` to see the accumulated results.

Everything the last three write accumulates under `.claude/cache/` (`skill-usage/canary-citations.jsonl`, `dispatch-probes/cache-runs.jsonl`, `dispatch-probes/ablation-runs.jsonl`), which is gitignored — that raw data is local to whoever ran the command and is never committed or shared. Only a short human-written summary of a run makes it into the repo, in the section below.

## Recorded measurements

A place to record what the live instruments actually reported, since the raw JSONL never leaves the machine that produced it. After running one of the commands above, add a dated one-liner here naming the agent, the figure, and the date — for example `reviewer: cache-read fraction 0.XX (YYYY-MM-DD)` or `reviewer: principle-i18n cited in N/M dispatches (YYYY-MM-DD)`. This section is hand-maintained; nothing generates it.

- **all agents: preload share 72.6% (222,950 agent-body chars vs. 589,781 preload chars,
  ~147,445 est. preload tokens across 22 agents) (2026-08-28)** — the static figure
  (`docs/dispatch-ledger.md`, condition 1). Worst offenders: `swe-workbench:senior-engineer` 90.8%,
  `swe-workbench:architect` 89.7%, `swe-workbench:reviewer` 86.9%.
- **senior-engineer: cache-read fraction 0.9982 on zai/glm-5.3 (2026-08-31)** — run 2 (repeat
  dispatch, same prefix) of the cache probe; cold run 0.0643. run 1 input=27959 cacheRead=1920
  ($0.0397), run 2 input=55 cacheRead=29824 ($0.0078).
- **architect: cache-read fraction 0.9994 on zai/glm-5.3 (2026-08-31)** — run 2 (repeat dispatch,
  same prefix); cold run 0.0586. run 1 input=30869 cacheRead=1920 ($0.0440), run 2 input=21
  cacheRead=32768 ($0.0088).
- **reviewer: cache-read fraction 0.9995 on zai/glm-5.3 (2026-08-31)** — run 2 (repeat dispatch,
  same prefix); cold run 0.0527. run 1 input=34515 cacheRead=1920 ($0.0491), run 2 input=19
  cacheRead=36416 ($0.0095).
  All three heaviest preloads on zai: repeat-dispatch cost dropped ~5× vs. cold, and the repeat-run
  cache-read fraction is ≥ 0.998 — the preloaded prefix is served almost entirely from cache on
  a back-to-back dispatch.
- **senior-engineer: cache-read fraction 0.0000 on openai-codex/gpt-5.6-sol, the configured
  default (2026-08-31)** — run 2 (repeat dispatch, same prefix); cold run also 0.0000. run 1
  input=29891 cacheRead=0 ($0.1525), run 2 input=29891 cacheRead=0 ($0.1566).
- **architect: cache-read fraction 0.0000 on openai-codex/gpt-5.6-sol, the configured default
  (2026-08-31)** — run 2 (repeat dispatch); cold run 0.0000. run 1 input=32803 cacheRead=0
  ($0.1715), run 2 input=32803 cacheRead=0 ($0.1646).
- **reviewer: cache-read fraction 0.0000 on openai-codex/gpt-5.6-sol, the configured default
  (2026-08-31)** — run 2 (repeat dispatch); cold run 0.0000. run 1 input=36452 cacheRead=0
  ($0.1828), run 2 input=36452 cacheRead=0 ($0.1829).
  On the default model the full ~30–36k-token preloaded prefix is billed fresh at full input
  price on every back-to-back dispatch — zero cache reads, unchanged cost run over run.
- **C3 decision: proceed (2026-08-31)** — R1 assessment: on the configured default model
  (openai-codex/gpt-5.6-sol) the repeat-dispatch cache-read fraction is 0.0000 for all three
  probed agents — ≤ 0.5, so R1 survives, demotion condition 4 becomes usable, and per issue
  #689's rule C3 (real-diff ablation corpus + sweep) proceeds. Recorded deliberately: the
  zai/glm-5.3 run above shows the opposite extreme (≥ 0.998, ~5× cost drop) — prefix caching is
  provider-dependent, so any future demotion decision resting on condition 4 must name the
  dispatch provider it was measured on. Both measurements are back-to-back dispatches inside
  the cache TTL — the caching-best-case shape the issue prescribed.

The cache-read fraction (condition 4) has now been collected (zai and default-model runs above,
2026-08-31) — the condition is satisfiable going forward. The citation rate (condition 2)
remains uncollected — it still requires a human-run instrument in an interactive terminal and
≥ 20 sampled dispatches, tracked in its follow-up. Condition 3 (ablation) is underway via the
C3 proceed decision above. All four conditions must still hold together before any demotion,
so **no skill can legitimately be demoted yet** — that is a statement about what hasn't been
measured, not that nothing should be.
