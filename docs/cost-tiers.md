# Cost tiers

Forward-looking convention for model assignment in swe-workbench agents. For the point-in-time snapshot that motivated this, see `cost-audit.md`.

## Tiers

| Tier | Alias | When to use | Examples |
|---|---|---|---|
| S (small) | `haiku` | Single-purpose fetch, format, or extract. Deterministic output from well-specified input. No cross-file reasoning or correctness judgment. | product-manager, tech-writer, test-writer, dependency-auditor |
| M (medium) | `sonnet` | Mechanical but judgment-bearing. Must weigh trade-offs, apply a pattern catalog, or preserve an invariant across steps. | debugger, refactorer, performance-tuner, accessibility-auditor, product-designer |
| L (large) | `sonnet` (default) or `opus` (with evidence) | High-stakes reasoning. Security exploitability, multi-system architecture, or correctness in concurrent / distributed settings. Opus only when measurable improvement is demonstrated. | reviewer, security-auditor, architect, senior-engineer |

**Default:** when in doubt, start at Tier M (`sonnet`). Downgrade to haiku only after confirming the task is mechanical. Promote to opus only with a measured A/B result.

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
   │           (security, architecture): Tier L, consider opus only
   │           with measured evidence.
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

**Keep on sonnet even if it looks simple:**
- Involves security exploitability assessment (security-auditor)
- Must preserve behavioral invariants across steps (refactorer, migrator)
- Output influences architecture or published contracts (architect, senior-engineer)

## When to revisit

Downgrade a Tier M agent to haiku when:
- At least 5 real-task invocations with no regression complaint (trial window: 14 days).
- No regression complaints tied to the agent.

Revert a haiku agent to sonnet when:
- A user-visible regression is traced to reasoning depth (not tool availability) within 14 days.
- PR description must note the reversion and the failing case.

Flag concentration in telemetry: if any single agent exceeds 15% of session token spend for more than 3 days, open a cost-audit follow-up issue.

## Philosophy

Model tier is a budget decision, not a quality signal. Haiku is not "worse" — it is the right tool for mechanical tasks. Defaulting everything to sonnet is wasteful; defaulting everything to haiku is brittle. Assign deliberately, measure, and adjust.
