---
name: observability-context
description: Fetch production observability signals from Sentry — error, exception, stack trace, regression, and alert data. Auto-loads on Sentry references. Returns message/culprit, first-seen, frequency, and a condensed stack trace, always labeled as Phase-1 framing, never a profile.
---

## When to invoke

Auto-loads when the caller references:

- **Sentry issue URL**: `sentry.io/organizations/<org>/issues/<id>/` or `<org>.sentry.io/issues/<id>/`.
- **Sentry event ID**: a raw event ID mentioned alongside a Sentry context clue (e.g. "Sentry event `abc123`").
- **Free-text production signal**: text describing a production error, exception, stack trace, regression, or alert — WHEN a Sentry MCP tool (`mcp__sentry__*`) is reachable in-session.

If no reference is present, exit cleanly.

## Adapters

### Sentry
- **Trigger:** Sentry issue URL (`sentry.io/organizations/<org>/issues/<id>/` or `<org>.sentry.io/issues/<id>/`), a raw Sentry event ID paired with a Sentry context clue, or free-text mention of a production error/exception/stack trace/regression/alert, gated on a reachable `mcp__sentry__*` tool.
- **Fetch:** `mcp__sentry__get_issue` with the issue ID or URL (aspirational — this plugin ships no Sentry MCP integration; this recipe activates only if the user has one connected). For a bare event ID, first resolve it via `mcp__sentry__get_event`.
- **Extract → block fields:** title/message and culprit → Message / culprit; `firstSeen` → First seen; event count and rate over the query window → Frequency; top stack frames or breadcrumb trail (condensed) → Stack / breadcrumb summary; issue permalink → Source.
- **Degrade:** If no `mcp__sentry__*` tool is reachable, emit `observability-context: Sentry MCP unavailable; proceeding without context.` Never fabricate or guess at error rates or stack content. On auth error, surface the raw error. On empty/404, say so; do not guess.

## Output format

One block per reference, prepended to caller context:

```
## Observability context: <issue ref or URL>

**Message / culprit:** ...
**First seen:** ...
**Frequency:** ... (event count / rate over window)
**Stack / breadcrumb summary:** ... (condensed, not a full raw dump)
**Evidence class:** production signal (Phase-1 framing) — NOT a profile; does not satisfy the profile-evidence gate.
**Source:** <URL>
```

## Absolute rules

- Strip secrets and PII (API tokens, user emails/IPs in stack traces or breadcrumbs) before returning.
- Cap at ~400 words per reference; summarize long stack traces without truncating mid-frame in a misleading way.
- Do not editorialize or infer root cause. Output the signal; downstream agents (e.g. `debugger`, `workflow-performance-investigation`) interpret it.
