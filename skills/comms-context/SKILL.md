---
name: comms-context
description: Fetch on-call and discussion context from Slack threads and PagerDuty incidents — participants, timeline, and status. Auto-loads on Slack permalinks or PagerDuty incident references. Keywords: Slack, thread, permalink, PagerDuty, incident, on-call, participants.
---

## When to invoke

Auto-loads when the caller references:

- **Slack permalink**: `<workspace>.slack.com/archives/<channel>/p<timestamp>`.
- **PagerDuty incident URL**: `<subdomain>.pagerduty.com/incidents/<id>`.
- **PagerDuty incident ID**: a bare incident ID mentioned alongside a PagerDuty context clue (e.g. "PagerDuty incident `PD-4521`"), when a PagerDuty MCP tool (`mcp__pagerduty__*`) is reachable in-session.
- **Free-text on-call signal**: text describing a page, on-call escalation, or Slack thread reference.

If no reference is present, exit cleanly.

## Adapters

### Slack permalink
- **Trigger:** Slack permalink URL (`<workspace>.slack.com/archives/<channel>/p<timestamp>`).
- **Fetch:** `mcp__slack__get_permalink_thread` with the channel and timestamp parsed from the URL (aspirational — this plugin ships no Slack MCP integration; this recipe activates only if the user has one connected). Resolve the permalink to a channel + timestamp, then fetch the root message and its thread replies.
- **Extract → block fields:** message author plus every distinct thread replier → Participants; message and reply timestamps in chronological order → Timeline; if the thread reaches a visible resolution or decision, summarize it, else "ongoing" → Status; the permalink itself → Source.
- **Degrade:** If no `mcp__slack__*` tool is reachable, emit `comms-context: Slack MCP unavailable; proceeding without context.` Never fabricate thread content or participants.

### PagerDuty incident
- **Trigger:** PagerDuty incident URL (`<subdomain>.pagerduty.com/incidents/<id>`), or a bare incident ID paired with a PagerDuty context clue — gated on a reachable `mcp__pagerduty__*` tool (no other skill claims PagerDuty IDs, so this trigger is unconditional once the URL or a PagerDuty-labeled ID is present; no cross-skill disambiguation is needed here).
- **Fetch:** `mcp__pagerduty__get_incident` with the incident ID or URL (aspirational — this plugin ships no PagerDuty MCP integration; this recipe activates only if the user has one connected). Fetch incident details, the escalation timeline, and current on-call responders.
- **Extract → block fields:** assignee plus on-call responders → Participants; triggered/acknowledged/resolved timestamps in order → Timeline; current incident status (triggered/acknowledged/resolved) → Status; incident URL → Source.
- **Degrade:** If no `mcp__pagerduty__*` tool is reachable, emit `comms-context: PagerDuty MCP unavailable; proceeding without context.` Never fabricate incident status or timeline. On auth error, surface the raw error. On empty/404, say so; do not guess.

## Output format

One block per reference, prepended to caller context:

```
## Comms context: <ref or URL>

**Participants:** ...
**Timeline:** ... (chronological, condensed)
**Status:** ...
**Source:** <URL>
```

## Absolute rules

- Strip secrets and PII (user emails, phone numbers in on-call schedules, tokens) before returning.
- Cap at ~400 words per reference; summarize long threads or timelines without truncating mid-message in a misleading way.
- Do not editorialize. Output the thread or incident; downstream agents interpret it.
