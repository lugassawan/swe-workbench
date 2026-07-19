---
name: ticket-context
description: Fetch ticket context from Jira (PROJ-123), Linear, Confluence, or GitHub (`#NNN`). Auto-loads on ticket references. Returns title, summary, acceptance criteria, links, and recent activity.
---

## When to invoke

Auto-loads when the caller references:

- **Jira key**: `[A-Z][A-Z0-9]+-\d+` — e.g. `PROJ-123`. A bare key routes to Jira by
  default; see the Linear adapter's Trigger field for the availability tiebreak that
  reroutes it when only a Linear MCP tool is reachable.
- **Atlassian Jira URL**: `*.atlassian.net/browse/<KEY>`.
- **Confluence URL**: `*.atlassian.net/wiki/spaces/...` or `*.atlassian.net/wiki/pages/...`.
- **Linear URL**: `linear.app/<workspace>/issue/<TEAM-N>` — routes here unconditionally.
- **GitHub issue/PR URL**: `github.com/<owner>/<repo>/(issues|pull)/\d+`.
- **GitHub short ref**: `#\d+` with current-repo context.

If no reference is present, exit cleanly.

## Adapters

### Jira issue
- **Trigger:** Jira key (`[A-Z][A-Z0-9]+-\d+`) or Atlassian Jira URL (`*.atlassian.net/browse/<KEY>`). A bare key routes here unless the Linear adapter's availability tiebreak applies.
- **Fetch:** First fetch in session: call `mcp__atlassian__getAccessibleAtlassianResources` for `cloudId` (cache for session). Then `mcp__atlassian__getJiraIssue` with the key.
- **Extract → block fields:** summary, issuetype, status, priority, description → Title/Type-Status/Summary; labels, components, acceptance-criteria (check description body if no dedicated field) → Acceptance criteria; linked issues via `mcp__atlassian__getJiraIssueRemoteIssueLinks` → Linked references; last 5 comments → Recent activity.
- **Degrade:** If Atlassian MCP unavailable, try `mcp__atlassian__fetch` with raw URL; if still failing, emit `ticket-context: Atlassian MCP unavailable; proceeding without context.` On auth error, surface the raw error; never fabricate. On empty/404, say so; do not guess.

### Confluence page
- **Trigger:** Confluence URL (`*.atlassian.net/wiki/spaces/...` or `*.atlassian.net/wiki/pages/...`).
- **Fetch:** Extract page ID from `/pages/<ID>` in the URL. Use `mcp__atlassian__getConfluencePage`; fall back to `mcp__atlassian__fetch` with raw URL if the ID is unclear.
- **Extract → block fields:** title → Title; version, body (rendered text) → Summary; footer comments via `mcp__atlassian__getConfluencePageFooterComments` (if any) → Recent activity.
- **Degrade:** If Atlassian MCP unavailable, try `mcp__atlassian__fetch` with raw URL; if still failing, emit `ticket-context: Atlassian MCP unavailable; proceeding without context.` On auth error, surface the raw error; never fabricate. On empty/404, say so; do not guess.

### GitHub issue or PR
- **Trigger:** GitHub issue/PR URL (`github.com/<owner>/<repo>/(issues|pull)/\d+`) or GitHub short ref (`#\d+`) with current-repo context.
- **Fetch:** Bash. Issue: `gh issue view <number> --repo <owner>/<repo> --json title,body,state,labels,assignees,comments,url`. PR: `gh pr view <number> --repo <owner>/<repo> --json title,body,state,labels,files,comments,url`. For `#NNN` short refs in the current repo, omit `--repo`.
- **Extract → block fields:** title → Title; state, labels → Type/Status; body → Summary/Acceptance criteria; assignees/files → Linked references; comments → Recent activity; url → Source.
- **Degrade:** If `gh` CLI is missing, emit `ticket-context: gh CLI unavailable; proceeding without context.` On auth error, surface the raw error; never fabricate. On empty/404, say so; do not guess.

### Linear
- **Trigger:** Linear issue URL — `linear.app/<workspace>/issue/<TEAM-N>[/...]` (unambiguous, always routes here). A bare `[A-Z]+-\d+` key routes here ONLY when a Linear MCP tool (`mcp__linear__*`) is reachable in-session AND no Atlassian MCP tool is reachable — otherwise a bare key stays routed to the Jira adapter above (zero regression to existing Jira routing; this is the explicit tiebreak rule).
- **Fetch:** `mcp__linear__*` tools (aspirational — this plugin does not ship a Linear MCP integration; this recipe activates only if the user has one connected). Fetch the issue by identifier or URL.
- **Extract → block fields:** title → Title; state, priority → Type/Status; description body → Summary/Acceptance criteria (or "not specified" if absent); labels, linked issues → Linked references; last activity → Recent activity; issue URL → Source.
- **Degrade:** If no `mcp__linear__*` tool is reachable, emit `ticket-context: Linear MCP unavailable; proceeding without context.` Never fabricate a Linear result, and never silently fall back to treating a `linear.app` URL as a Jira key.

## Output format

One block per reference, prepended to caller context:

```
## Ticket context: <KEY or #NUM or short URL>

**Title:** ...
**Type / Status:** ...
**Summary:** ... (1–3 sentences)
**Acceptance criteria / Definition of done:** ... (bulleted if present, otherwise "not specified")
**Linked references:** ...
**Recent activity:** ...
**Source:** <URL>
```

## Absolute rules

- Strip secrets and PII (API tokens, email addresses in comments) before returning.
- Cap at ~400 words per reference; summarize long descriptions without truncating mid-sentence.
- Do not editorialize. Output the ticket; downstream agents interpret it.
