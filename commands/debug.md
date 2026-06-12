---
description: Diagnose a bug, failing test, or unexpected behavior — root-cause first, minimal fix, regression test. Performance-shaped symptoms (slow, latency, profiling) are routed to workflow-performance-investigation via one clarifying question.
argument-hint: <symptom, failing test, or error, optionally with a ticket ref> [--grill | --standard]
---

Symptom: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.

**Performance routing.** After resolving the mode, check whether the symptom is performance-shaped before proceeding. A symptom is performance-shaped when it describes speed, latency, throughput, or resource exhaustion without an assertion failure or incorrect output — key vocabulary (case-insensitive, stem-matched): `slow`, `too slow`, `latency`, `throughput`, `cpu`, `memory leak`, `oom`, `profil*`, `benchmark`, `bottleneck`, `perf`, `performance`, `high memory`, `resource exhaustion`, `takes too long`.

If the symptom is performance-shaped:

1. If grill-me mode was active and the `## Resolved decisions` block already classifies the symptom as performance or correctness, use that classification and skip the `AskUserQuestion`.
2. Otherwise call `AskUserQuestion` — header **Symptom type**, question "Is this a performance investigation or a correctness bug?", two options:
   - **Performance investigation** — "Activate `swe-workbench:workflow-performance-investigation`: profile-first runbook (baseline → profile → ranked hotspots → one change → before/after measurement → regression guard)."
   - **Correctness bug** — "Proceed with the debugger: root-cause first, minimal fix, regression test."
3. On **Performance investigation**: activate `swe-workbench:workflow-performance-investigation` and stop — do not continue to browser diagnostics or debugger delegation.
4. On **Correctness bug**: continue with the browser diagnostic step below.

If the symptom is not performance-shaped: skip this step entirely.

**Browser diagnostic step (web-UI symptoms only).** Before delegating, check whether the symptom indicates a browser / web-UI context (e.g., mentions a rendered page, console error, XHR/fetch failure, visual regression, or DOM state). If it does:

1. **Gate** — check whether a Chrome backend is available in this session. A Chrome backend is one of:
   - `chrome-devtools-mcp` (`read_console_messages`, `read_network_requests` tools reachable), OR
   - Claude-in-Chrome (`mcp__claude-in-chrome__read_console_messages` tool reachable).

   If the symptom is web-UI but **no Chrome backend is connected**, stop immediately and return:

   ```
   BLOCKED: Browser diagnostics requested but no Chrome backend is connected.
   To capture console and network evidence, run `claude mcp add chrome-devtools-mcp npx chrome-devtools-mcp@latest`
   Then reconnect and retry, or re-run /debug without a browser context to skip this step.
   ```

2. **Capture** — if a Chrome backend is present, collect:
   - Console messages (errors, warnings, and relevant info) via `read_console_messages`.
   - Network request failures or unexpected responses via `read_network_requests`.
   - Summarise into a structured block:

   ```
   ## Browser evidence
   ### Console
   <filtered console output — errors and warnings>
   ### Network
   <failed or anomalous requests with status codes>
   ```

3. **Prepend** this `## Browser evidence` block to the delegation context below (same position as a ticket-context summary). The debugger agent will incorporate it as boundary evidence before forming hypotheses.

Non-web symptoms (backend panics, CLI failures, test assertion errors): skip this step entirely — no gate, no prompt.

Delegate to the `debugger` subagent. Its output must include:

1. **Repro** — exact steps, inputs, and the observed failure (command, stack trace, or assertion delta).
2. **Hypotheses** — 2–3 candidate causes, each falsifiable with the observation that would confirm or rule it out.
3. **Root cause** — the single cause supported by concrete evidence (log line, stack frame, state diff). No speculation.
4. **Minimal fix** — smallest behavior-changing patch that resolves the root cause; call out what it deliberately does NOT touch.
5. **Regression test** — the test that fails before the fix and passes after. Name it and its location.
6. **SOLID / Clean-Arch risks** — whether the bug's shape signals a principle violation, and whether the minimal fix papers over it.

Absolute rule: no fix without a failing test first. This command changes behavior to match spec — it is not a refactor.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Since `/debug` always produces a fix (file edits), Mode A always applies here.
