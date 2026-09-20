# Cost tiers

Forward-looking convention for model assignment in swe-workbench agents. For the point-in-time snapshot that motivated this, see `cost-audit.md`.

## Tiers

| Tier | Alias | When to use | Examples |
|---|---|---|---|
| S (small) | `haiku` | Single-purpose fetch, format, or extract. Deterministic output from well-specified input. No cross-file reasoning or correctness judgment. | product-manager, tech-writer, test-writer, dependency-auditor |
| M (medium) | `sonnet` | Mechanical but judgment-bearing. Must weigh trade-offs, apply a pattern catalog, or preserve an invariant across steps. | debugger, refactorer, performance-tuner, accessibility-auditor, product-designer |
| L (large) | `sonnet` (default) or `opus` (promoted) | High-stakes reasoning. Security exploitability, multi-system architecture, or correctness in concurrent / distributed settings. | reviewer, security-auditor, architect, senior-engineer, migrator |

**Default:** when in doubt, start at Tier M (`sonnet`). Downgrade to haiku only after confirming the task is mechanical. Promote to opus via either gate below — this repo has no A/B harness or telemetry, so **reasoned promotion is the primary path**, not a fallback:

- **Measured** — an A/B result showing opus measurably outperforms sonnet on the agent's actual task.
- **Reasoned** — the agent matches a forcing function below, argued explicitly against the frequency×delta veto (a high-frequency agent needs a materially stronger case than an occasional one) and recorded as a one-line keep/bump rationale alongside the change.

## Where the field lives

In the agent's YAML frontmatter, bare alias form, with a portable reasoning-effort alias
immediately after it:

```yaml
---
name: my-agent
model: haiku     # or sonnet, or opus
effort: high     # or low, medium, high, xhigh, max
tools: ...
---
```

`effort:` is portable across harnesses, not Pi-specific: Claude Code reads it directly as
reasoning effort, alongside `model:`. Every agent declares the default for its tier —
`DEFAULT_TIER_EFFORT` in `pi/extensions/model-policy.ts`:

| Model alias | Default effort |
|---|---|
| `haiku` | `high` |
| `sonnet` | `xhigh` |
| `opus` | `high` |

Skills have no `model:`/`effort:` field — they are injected as context into the invoking session
and inherit its model and reasoning effort.

## How to choose

```
Does the agent require multi-step reasoning, cross-file synthesis,
or security/correctness judgment?
   │
   ├── Yes ──► Tier M or L (sonnet). For high-stakes correctness
   │           (security, architecture): Tier L, promote to opus
   │           when a forcing function applies (measured or reasoned).
   │
   └── No ──► Is the output deterministic given well-specified input?
                 │
                 ├── Yes ──► Tier S (haiku). Candidate for downgrade.
                 │
                 └── Unsure ──► Tier M (sonnet). Revisit after use.
```

**Forcing functions for haiku:**
- Output is a structured document from template + inputs (product-manager, tech-writer)
- Output is idiomatic code generated from a behavioral spec (test-writer)
- Output is a tabular report extracted from manifest files (dependency-auditor)

**Keep on sonnet even if it looks high-stakes:**
- Behavior-preservation is enforced by a hard test gate, not judgment alone (refactorer — green between every step or revert)
- Root cause is confirmed by a failing-then-passing regression test, not self-authored reasoning alone (debugger)
- Output flows through Phase 3 Verify + Phase 4 Review before it can land (code-impl)

**Forcing functions for opus:**
- Output is a durable published artifact (ADR/RFC) with no automatic downstream gate — a wrong constraint or unnamed risk becomes precedent (architect)
- A phase is explicitly not reversible, and the agent authors its own advance-gate metrics — a blind spot in its call-site mapping propagates into the very check meant to catch it (migrator)
- A wrong judgment is a security clearance that ships a real, unnoticed vulnerability (security-auditor)
- The agent is the explicit escalation target for an unresolved architectural fork another worker couldn't judge itself, and the escalation exists precisely because no other worker or reviewer in the pipeline can independently validate the trade-off analysis — criterion 3 (absence-detection), not 1+2 (senior-engineer)

None of these apply on every PR — each is invoked occasionally by design, which is what keeps the frequency×delta veto from blocking the promotion.

## When to revisit

Downgrade a Tier M agent to haiku when:
- At least 5 real-task invocations with no regression complaint (trial window: 14 days).
- No regression complaints tied to the agent.

Revert a haiku agent to sonnet when:
- A user-visible regression is traced to reasoning depth (not tool availability) within 14 days.
- PR description must note the reversion and the failing case.

Revert an opus agent to sonnet when:
- 14 days pass with no case where the extra reasoning depth visibly changed the outcome versus a comparable sonnet run.
- The forcing function that justified the promotion no longer applies (e.g. a downstream gate was added that now catches what previously shipped silently).
- PR description must note the reversion and cite which of the two conditions triggered it.

Flag concentration in telemetry: if any single agent exceeds 15% of session token spend for more than 3 days, open a cost-audit follow-up issue.

## On the Pi Coding Agent

`pi/extensions/model-policy.ts`'s `MODEL_POLICY` resolves an agent's `model: haiku|sonnet|opus`
tier plus its `effort: low|medium|high|xhigh|max` frontmatter to an **exact** Pi model id and an
effective thinking level, not by cost — an explicit divergence from this doc's cost-driven S/M/L
framing, which exists to inform a *choice* of tier, not to reproduce it as a runtime lookup. Model
selection is exact id equality against the candidate pool — never a substring or shortest-match
heuristic — so a catalog reshuffle or a new sibling id can never silently re-point a tier at the
wrong model.

Resolution only covers three providers today — `anthropic`, `openai-codex`, and `zai` — each with
an exact model id per tier. Feeding each tier's default effort (the table above) through
`MODEL_POLICY` reproduces this matrix:

| Tier | anthropic | openai-codex | zai |
|---|---|---|---|
| opus | `claude-opus-5:high` | `gpt-5.6-sol:high` | `glm-5.3:max` |
| sonnet | `claude-sonnet-5:xhigh` | `gpt-5.6-terra:xhigh` | `glm-5.3:high` |
| haiku | `claude-haiku-4-5:high` | `gpt-5.6-luna:high` | `glm-5.2-highspeed:high` |

**Portable vs. effective effort.** The `effort:` value in an agent's frontmatter is *portable* —
the same value Claude Code reads directly as reasoning effort. On Pi, `MODEL_POLICY` translates it
into an *effective* thinking level per (provider, tier) cell. For `anthropic` and `openai-codex`
this translation is the identity (portable effort passes straight through). For `zai`, it isn't:
`glm-5.3` serves both the `opus` and `sonnet` tier, so thinking level is the only axis left to keep
`opus` dispatch strictly deeper than `sonnet` dispatch for the same nominal effort — `opus`'s table
shifts effort up toward `max`, `sonnet`'s shifts it down toward `low`, both clamped at their end.

**Z.AI clamp caveat (resolved).** The effective thinking level `MODEL_POLICY` emits used to be
*nominal only* — the installed Pi SDK clamped it further per what its own bundled catalog
*declared* the target model supports, which didn't match what the model actually supports. Per
Z.AI's own spec, `glm-5.3` always reasons and genuinely supports `max` as one of its three real
effort levels (`low`/`high`/`max`); through `@earendil-works/pi-coding-agent` 0.84.2 the catalog
pin carried no `thinkingLevelMap` for it at all, so *that dependency's* clamp logic reduced the
nominal `zai.opus` value of `max` down to `high` at dispatch time — identical, then, to
`zai.sonnet`'s nominal (and already-recognized) `high`. As of the 0.84.3 bump, the pinned catalog
now ships a real `thinkingLevelMap` for `glm-5.3` (`low`/`high`/`max`), so `zai.opus`'s nominal
`max` dispatches as genuine `max` — strictly deeper than `zai.sonnet`'s `high`, no longer clamped
down to it. The opus/sonnet split on Z.AI is therefore real, dispatch-visible behavior now, not
purely nominal. `tests/test_pi_contract.py` pins this directly against the bundled catalog data,
so a future catalog change that drops `glm-5.3`'s `thinkingLevelMap` again fails that test
loudly — the signal to revisit this caveat once more, not silently drift past.

**Fallback.** For any provider outside the three above, an unrecognized/missing `model:` tier, an
unrecognized/missing `effort:` value, or a tier/provider combination whose exact model id isn't in
the candidate pool, `pi/extensions/subagent.ts`'s `task` tool falls back to the parent session's
own current model and thinking level, unchanged — never to something else, never to a new
provider, `baseUrl`, or API key. Each of these four cases carries a structured reason
(`provider-unsupported`, `tier-unknown`, `effort-unknown`, or `model-unavailable`) surfaced in the
tool result's `details`, plus a visible warning — a UI notification when available, and always a
one-line `[swe-workbench] …` block in the tool result content so headless (print-mode) sessions
see it too. (The dispatched child's own parent session having no active model at all is a
separate, unrelated case — `--model`/`--thinking` are both simply omitted, with no fallback
reason and no warning, since there is no model to have fallen back from.)

There is no runtime, user-global, or project-local override surface for any of this — `MODEL_POLICY`
is a fixed table in this plugin's own reviewed source, not a config file. See
`docs/decisions-task-dispatch.md` for the full trust-boundary rationale (hardcoded in reviewed
source, not a runtime-editable settings file, specifically to avoid becoming an exfiltration
primitive) and why exact ids strengthen that boundary rather than weaken it.

## Philosophy

Model tier is a budget decision, not a quality signal. Haiku is not "worse" — it is the right tool for mechanical tasks. Defaulting everything to sonnet is wasteful; defaulting everything to haiku is brittle. Assign deliberately, measure, and adjust.
