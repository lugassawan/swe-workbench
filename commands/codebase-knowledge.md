---
description: Present a structured knowledge document for this codebase — architecture overview, module map, public API surfaces, and patterns. Knowledge-presentation only (no defect ranking). Use /swe-workbench:audit-codebase for defect sweeps; /swe-workbench:document for generating new prose docs.
argument-hint: "[path]"
---

Produce a structured knowledge document for this codebase.

## Step 1 — Parse arguments

From `$ARGUMENTS`, extract:

- **Optional path** — a token is treated as a path if it contains `/`, starts with `.`, or matches an existing directory in the repo; otherwise treat the entire argument string as natural-language context with no path scoping. If a path is identified, scope all phases to that path and its descendants; if absent, use the repo root.
- **Ticket ref** — scan first: any token matching `#\d+`, `[A-Z]+-\d+`, or an `atlassian.net`/GitHub URL is a ticket ref. Collect the first match and remove it from the remaining argument string before further parsing; ignore if none.

## Step 2 — Ticket context (when a ref is present)

If a ticket ref was found in Step 1, invoke `swe-workbench:ticket-context` with that ref and prepend its summary to the context passed in Step 3.

## Step 3 — Invoke workflow skill

Pass the parsed path (or `.` if absent) to `swe-workbench:workflow-codebase-knowledge`:

> "Path: `<path>`."

Append the ticket-context summary from Step 2 if present.

The skill handles all five phases (Scope → Module map → Public API surfaces → Patterns → Render) and produces the structured knowledge document. This command does not produce Plan-mode output — the sweep is read-only by definition.
