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

In the agent's YAML frontmatter, bare alias form:

```yaml
---
name: my-agent
model: haiku     # or sonnet, or opus
tools: ...
---
```

Skills have no `model:` field — they are injected as context into the invoking session and inherit its model.

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

`pi/extensions/model-tier.ts`'s `MODEL_TIER_TABLE` resolves an agent's `model: haiku|sonnet|opus`
frontmatter to a concrete Pi model **by name** (substring match against `Model.id`, e.g.
`"opus"` → `claude-opus-5`), not by cost — an explicit divergence from this doc's cost-driven S/M/L
framing, which exists to inform a *choice* of tier, not to reproduce it as a runtime lookup.
Resolution only covers three providers today — `anthropic`, `openai-codex`, and `zai` — each with
its own name patterns per tier. For any other provider, or a tier/provider combination with no
matching candidate, `pi/extensions/subagent.ts`'s `task` tool silently falls back to the parent
session's own current model, unchanged; it never introduces a new provider, `baseUrl`, or API key.
See `docs/plugin-platform-decisions.md` §9 for the full trust-boundary rationale (the table is
hardcoded in reviewed source, not a runtime-editable settings file, specifically to avoid becoming
an exfiltration primitive).

## Philosophy

Model tier is a budget decision, not a quality signal. Haiku is not "worse" — it is the right tool for mechanical tasks. Defaulting everything to sonnet is wasteful; defaulting everything to haiku is brittle. Assign deliberately, measure, and adjust.
