---
name: principle-postmortem
description: Postmortem principles — blameless culture, root cause analysis (5 Whys, Fishbone), incident document structure, action-item discipline, MTTD/MTTR metrics. Auto-load when running a blameless review, structuring an incident report, facilitating RCA, tracking action items after an outage, or improving incident response processes.
---

# Postmortem

Incidents are inevitable. A postmortem converts failure into systemic learning — the goal is not to assign blame but to close the gap between what the system can do and what the environment demands. The prevent → detect → learn triad is incomplete without this phase.

Cross-references: `principle-resiliency` (prevent), `principle-observability#SLI / SLO / Error Budget` (detect / MTTD-MTTR framing), `principle-release-engineering#Rollback` (remediation action items).

## Blameless Culture

Blame suppresses signal. When individuals fear punishment, they conceal information, underreport near-misses, and avoid risky-but-necessary work. Blameless postmortems operate from the assumption that everyone acted rationally given the information and tools available to them at the time.

Guiding principles:

- **"The system allowed it"** — if a person could cause an outage, the system lacked the guardrails to prevent it. The fix belongs in the system, not the person.
- **Psychological safety** — participants must feel safe sharing the full sequence of events, including their own mistakes. Facilitation owns this; interrupt any language that assigns personal fault.
- **Hindsight bias** — it is easy to see the right move after the fact. Explicitly reconstruct the information available at each decision point; do not evaluate decisions using information that only became visible later.
- **Counterfactual fairness** — "if only they had done X" is only valid if X was a realistic, well-understood option at the time. If X required information no one had, the real gap is in the information architecture.
- **Separate the review from personnel processes** — postmortems feed the improvement backlog, not performance reviews.

## Root Cause Analysis

A single proximate cause is almost never the full story. Three distinct layers exist:

- **Trigger** — the immediate event that precipitated the incident (a deployment, a traffic spike, a configuration change).
- **Condition** — the pre-existing state that made the system vulnerable to that trigger (an untested code path, a missing circuit breaker, a stale cache TTL).
- **Root cause** — the systemic gap that allowed the condition to persist undetected (absent pre-deploy checklist, no SLO alert on the affected path, no load test in CI).

Fixing only the trigger prevents the exact same incident; fixing the root cause prevents a class of incidents.

### 5 Whys

Iteratively ask "why did this happen?" until you reach a controllable, systemic factor. Each answer becomes the premise of the next question.

- Start from the trigger, not the symptom.
- Stop when the answer is "we had no process / no visibility / no incentive to catch this" — that is a root cause.
- Document each why-answer pair; the chain is the evidence.
- Beware shallow stopping: "human error" is almost never a root cause — ask why the error was possible.

### Fishbone (Ishikawa)

Use when the incident has multiple, parallel contributing factors that do not form a clean causal chain. Draw a central "spine" (the effect) with branches for contributing factor categories:

- **People** — training gaps, handoff failures, role ambiguity.
- **Process** — missing runbooks, inadequate on-call rotations, unclear escalation paths.
- **Tooling** — alert fatigue, missing dashboards, slow deploy pipelines, inadequate rollback mechanisms.
- **Environment** — dependency failures, infrastructure limits, third-party SLA violations.
- **Measurement** — absent or lagging metrics, poorly calibrated SLOs, no baseline data.

Each branch can have sub-branches. Fishbone complements 5 Whys: use 5 Whys to drill into the most critical branch found by the Fishbone diagram.

## Postmortem Document Structure

Time-box the draft to **24–72 hours** after mitigation while memory is fresh.

Required sections, in order:

- **Title + Severity + Status** — descriptive title, severity tier (P0–P3 or equivalent), draft/reviewed/closed.
- **Timeline** — chronological sequence of events with UTC timestamps: when did the condition begin, when was the incident detected, when were responders paged, when was mitigation applied, when was the incident closed.
- **Impact** — who was affected, how many users/requests/dollars, duration. Quantify; avoid vague language.
- **Root cause** — one paragraph. Uses the trigger/condition/root-cause framing from above.
- **Contributing factors** — list of conditions that compounded the impact or delayed detection.
- **Lessons learned** — what went well (do not skip this; it anchors future behavior), what went poorly, where there was luck.
- **Action items** — see Action-Item Discipline below.

## Action-Item Discipline

"Improve monitoring" is not an action item. An action item is a specific, measurable change assigned to a named owner with a due date.

Every action item must answer three questions:

1. **What exactly will change?** — name the alert, the runbook section, the circuit-breaker threshold, the test case.
2. **Who is the owner?** — one person; committees do not ship.
3. **When is it done?** — a specific date or sprint, not "soon".

Categorize by impact tier:

- **Prevent** — eliminates the root cause (adds the missing guard, removes the dangerous code path).
- **Detect** — closes the detection gap (adds the missing SLO alert, reduces MTTD).
- **Mitigate** — reduces blast radius for the next occurrence (adds a kill-switch, improves rollback speed).

Track in the same system as engineering work (sprint backlog, issue tracker). Postmortem action items that live only in a doc rot and get forgotten.

## Incident Metrics

Track over rolling quarters to surface trends, not just individual incidents:

- **MTTD (Mean Time To Detect)** — gap between incident start and first alert. Feeds `principle-observability` SLO work; high MTTD signals missing or miscalibrated alerts.
- **MTTR (Mean Time To Recover)** — gap between detection and full mitigation. Feeds `principle-resiliency` rollback and degradation work; high MTTR signals slow deploy pipelines or inadequate runbooks.
- **Repeat-incident rate** — same root cause recurring within a quarter. The single strongest signal that action items are not being completed or are not addressing the right layer.

Review trends in retros, not just in individual postmortems. A rising MTTD means the observability investment is not keeping pace with system complexity.

## When a Postmortem is Overkill

Not every incident warrants a full postmortem. Reserve the full process for:

- Customer-visible impact lasting more than a few minutes (adjust threshold to your SLO tier).
- Incidents that required escalation beyond the on-call engineer.
- Any incident in the same root-cause class as a prior postmortem (repeat signal).
- Incidents where the responder felt they were close to making a much larger mistake.

For minor incidents below this threshold, a lightweight 5-line "incident note" (what happened, what was done, follow-up if any) is sufficient. The overhead of a full postmortem can discourage reporting if applied indiscriminately.

## Red Flags

| Flag | Problem |
|---|---|
| The postmortem names an individual as the root cause | Blame, not analysis. The system allowed the action; the fix belongs in the system. |
| Action items have no owner | Orphaned tasks. Without an owner, no one ships. |
| Action items have no due date | Perpetually pending. No due date means no accountability. |
| The doc was written more than a week after the incident | Memory has decayed; the timeline will be inaccurate and contributing factors will be missed. |
| "Human error" appears as a root cause | Premature stop. Ask why the error was possible; the answer is the real root cause. |
| The incident timeline has gaps longer than 30 minutes with no annotation | Responders were working but not communicating; the timeline is incomplete. |
| Action items are not tracked in the engineering backlog | Postmortem action items that live only in a doc get forgotten. Link every item to a ticket. |
| No "what went well" section | Anchoring bias — teams that only record failures fail to reinforce behavior worth repeating. |
