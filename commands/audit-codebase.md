---
description: Cold-start, time-boxed, multi-domain audit sweep — surfaces ranked findings with reasoning chains across security, performance, reliability, tooling, and testing
argument-hint: "[--time-box <duration>] [--scope <list>] [--depth <quick|standard|deep>] [--top-n <int>] [optional ticket ref]"
---

Cold-start audit of this codebase across multiple domains.

## Step 1 — Parse arguments

From `$ARGUMENTS`, extract:

- `--time-box <duration>` — default `30m`. Any trailing `m`/`h` suffix is accepted (e.g. `30m`, `2h`).
- `--scope <list>` — default `all`. Comma-separated domain names: `security`, `perf`, `reliability`, `tooling`, `testing`, or `all`.
- `--depth <quick|standard|deep>` — default `standard`. Controls fan-out behaviour:
  - `quick` — single-pass auditor, no fan-out.
  - `standard` — single-pass auditor, no fan-out.
  - `deep` — auditor + security-auditor on top-N security findings + debugger on top-N reproducing reliability findings.
- **Ticket ref** — scan first: any token matching `#\d+`, `[A-Z]+-\d+`, or an `atlassian.net`/GitHub URL is a ticket ref. Collect first match and remove it from the remaining argument string before further parsing; ignore if none.
- `--top-n <int>` — default `10`. After ticket-ref tokens are consumed, any bare integer in the remaining `$ARGUMENTS` not preceded by a flag name is treated as `--top-n` (integer sniff, same convention as `commands/review.md`).

## Step 2 — Ticket context (when a ref is present)

If a ticket ref was found in Step 1, invoke `swe-workbench:ticket-context` with that ref and prepend its summary to the audit context passed in Step 3.

## Step 3 — Invoke workflow skill

Pass the parsed values as plain prose to `swe-workbench:workflow-codebase-audit`:

> "Time-box: `<time-box>`. Scope: `<scope>`. Depth: `<depth>`. Top-N: `<top-n>`."

Append the ticket-context summary from Step 2 if present.

The skill handles phase orchestration, schema enforcement, fan-out (deep mode), and ranked rendering. This command does not produce Plan-mode output — the audit is read-only by definition.
