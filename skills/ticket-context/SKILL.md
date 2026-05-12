---
name: ticket-context
description: Fetch ticket context from Jira (PROJ-123), Confluence, or GitHub (`#NNN`). Auto-loads on ticket references. Returns title, summary, acceptance criteria, links, and recent activity.
---

## When to invoke

Auto-loads when the caller references:

- **Jira key**: `[A-Z][A-Z0-9]+-\d+` — e.g. `PROJ-123`.
- **Atlassian Jira URL**: `*.atlassian.net/browse/<KEY>`.
- **Confluence URL**: `*.atlassian.net/wiki/spaces/...` or `*.atlassian.net/wiki/pages/...`.
- **GitHub issue/PR URL**: `github.com/<owner>/<repo>/(issues|pull)/\d+`.
- **GitHub short ref**: `#\d+` with current-repo context.

If no reference is present, exit cleanly.

## Fetch recipes

### Jira issue

First fetch in session: call `mcp__atlassian__getAccessibleAtlassianResources` for `cloudId` (cache for session). Then `mcp__atlassian__getJiraIssue` with the key. Extract: summary, issuetype, status, priority, description, labels, components, acceptance-criteria (check description body if no dedicated field), linked issues via `mcp__atlassian__getJiraIssueRemoteIssueLinks`, last 5 comments.

### Confluence page

Extract page ID from `/pages/<ID>` in the URL. Use `mcp__atlassian__getConfluencePage`; fall back to `mcp__atlassian__fetch` with raw URL if ID unclear. Extract: title, version, body (rendered text), footer comments via `mcp__atlassian__getConfluencePageFooterComments` if any.

### GitHub issue or PR

Use Bash:
- Issue: `gh issue view <number> --repo <owner>/<repo> --json title,body,state,labels,assignees,comments,url`
- PR: `gh pr view <number> --repo <owner>/<repo> --json title,body,state,labels,files,comments,url`

For `#NNN` short refs in the current repo, omit `--repo`.

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

## Degradation

| Condition | Action |
|---|---|
| Atlassian MCP unavailable | Try `mcp__atlassian__fetch` with raw URL; if still failing, emit `ticket-context: Atlassian MCP unavailable; proceeding without context.` |
| `gh` CLI missing | Emit `ticket-context: gh CLI unavailable; proceeding without context.` |
| Auth error | Surface the raw error; never fabricate. |
| Fetch returns empty or 404 | Say so; do not guess. |

## Absolute rules

- Strip secrets and PII (API tokens, email addresses in comments) before returning.
- Cap at ~400 words per reference; summarize long descriptions without truncating mid-sentence.
- Do not editorialize. Output the ticket; downstream agents interpret it.
