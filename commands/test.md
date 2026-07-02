---
description: Invoke the test-writer subagent to add focused, behavioural tests in the target language's idiom. Pass --mode e2e (or --e2e) to run the browser-driven E2E pipeline instead, or --mode e2e-live for an ephemeral, human-watched browser walkthrough with no spec file written.
argument-hint: <file, function, or module> [--mode e2e | --mode e2e-live | --e2e]
---

Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

## Mode resolution

Parse `$ARGUMENTS` for `--mode e2e-live`, `--mode e2e`, or `--e2e`. Match `--mode e2e-live` by exact token **first** — a substring match on `e2e` would false-trip the e2e branch since `e2e-live` contains `e2e`:

- **E2E-live mode** (`--mode e2e-live` present): strip the flag from the target and follow the **E2E-live path** below.
- **E2E mode** (`--mode e2e` or `--e2e` present): strip the flag from the target and follow the **E2E path** below. This also means a bare `--e2e-live` attempt (unsupported — only `--mode e2e-live` is recognized) must not be treated as `--e2e`.
- **Default mode** (no flag, or any unrecognized flag such as a bare `--e2e-live`): follow the **Unit path** below with the unrecognized token left in the target text — there is no dedicated error path for unsupported flags.

---

## E2E path (`--mode e2e`)

### Hard gate

Before dispatching any agents, verify that Playwright MCP is available in this session by checking whether `browser_snapshot` (or equivalent `browser_*` tools under the MCP install prefix) is reachable.

If Playwright MCP is **not connected**, stop immediately and return:

```
BLOCKED: Playwright MCP not connected — run `claude mcp add playwright npx @playwright/mcp@latest`, restart Claude Code, and retry.
```

Do not delegate to any agent until the gate passes.

### Pipeline

Dispatch the following two-agent pipeline in sequence:

1. **`e2e-test-writer`** — explores the live app via Playwright MCP, authors durable spec files, and produces a behaviour inventory + spec paths.
2. **`e2e-test-verifier`** — receives the spec paths from step 1, runs them via the project's detected E2E command, and distrusts false-greens.

If `e2e-test-writer` returns a `BLOCKED:` sentinel, surface it to the user and stop — do not invoke `e2e-test-verifier`.

If `e2e-test-verifier` returns a `BLOCKED:` sentinel, surface it to the user.

### E2E output contract

Surface the combined output:

1. **Behaviour inventory** (from writer) — numbered list of behaviours explored.
2. **Spec file location(s)** (from writer) — where the new specs live.
3. **Run result** (from verifier) — command, exit code, per-spec verdict.
4. **Suspect passes** (from verifier) — any false-green diagnoses.
5. **What was NOT covered** (from writer + verifier) — with reasons.

---

## E2E-live path (`--mode e2e-live`)

An ephemeral, human-watched demo — drive the live app in a headed, paced browser so a human can
watch the walkthrough in real time. Unlike `--mode e2e`, this path writes **no spec file** and
invokes **no subagent**: there is no durable artifact to author and no false-green to adversarially
distrust, because the human watching the browser *is* the verifier. Drive it inline from this
command in the main thread so the step-by-step narration stays in sync with the browser the human
sees — a subagent's narration would land in an isolated transcript instead.

### Hard gate (backend-agnostic)

Before driving anything, verify that a browser-automation MCP is connected — **either**:

- **Playwright MCP**: `browser_snapshot` (or another `browser_*` tool) is reachable, or
- **claude-in-chrome**: `mcp__claude-in-chrome__*` tools are reachable (load via `ToolSearch` first
  if deferred — e.g. `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp`).

If **neither** backend is available, stop immediately and return:

```
BLOCKED: no browser-automation MCP connected — connect one and retry:
  Playwright MCP:    claude mcp add playwright npx @playwright/mcp@latest
  claude-in-chrome:  enable the Claude-in-Chrome browser extension
```

Do not drive the browser until the gate passes.

### Drive inline (no subagent)

Using whichever backend passed the gate, narrate each step in the main thread as you perform it —
e.g. "navigating to /login… filling credentials… asserting dashboard visible" — so the narration is
synchronized with the headed browser the human is watching:

1. Navigate to the target URL (starting the dev server first if the target is a local flow, not a
   live URL).
2. Snapshot the page (`browser_snapshot` or `mcp__claude-in-chrome__read_page`).
3. Interact — click, fill, wait for a condition — using the active backend's tools (Playwright
   `browser_click` / `browser_type` / `browser_wait_for`, or claude-in-chrome
   `mcp__claude-in-chrome__computer` / `mcp__claude-in-chrome__form_input`).
4. Snapshot again to confirm the resulting state, and narrate what was observed.
5. Repeat for each step of the flow described in `$ARGUMENTS`.

**Paced & observable:** keep the browser headed and insert deliberate brief pauses between steps so
a human can follow along. This mode **relaxes** the test-writer's "never `sleep()`" rule — that rule
exists to keep durable specs deterministic and fast; a live demo is meant to be paced for a human,
not optimized for CI speed.

### GIF recording (backend-dependent, best-effort)

- **claude-in-chrome active:** record the walkthrough with `mcp__claude-in-chrome__gif_creator` —
  give it a meaningful filename and capture extra frames before/after actions per that tool's own
  guidance.
- **Playwright MCP active:** no native recording tool exists yet — capture a `browser_take_screenshot`
  frame per step instead, and note GIF stitching as optional/future work.
- Recording is best-effort: never let a recording failure fail the demo itself.

### Ephemeral invariant

This path writes **no** spec file and produces no durable code artifact. A recorded GIF, if any, is
a shareable demo capture — not a test artifact. This is the property that distinguishes
`--mode e2e-live` from `--mode e2e`.

### Teardown

Close the browser session at the end — `browser_close` (Playwright) or the claude-in-chrome tab close
(`mcp__claude-in-chrome__tabs_close_mcp`) — so no session is left open. Avoid triggering blocking JS
dialogs (alerts/confirms/prompts) during the walkthrough, per claude-in-chrome guidance.

### E2E-live output contract

Surface:

1. **Walkthrough recap** — numbered list of steps performed and the state observed at each step.
2. **GIF path**, if one was recorded — omit this line if recording wasn't available.
3. An explicit **"No spec file written — ephemeral demo"** line.

No verifier is invoked for this path.

---

## Unit path (default)

Delegate to the `test-writer` subagent. Its output must include:

1. **Behaviour inventory** — numbered list of all behaviours identified.
2. **Test file location and naming** — where the new tests live.
3. **Tests written** — count and names.
4. **Run result** — command used and pass / fail summary.
5. **Untested behaviours and why** — e.g., "covered by integration test", "trivial getter".

Absolute rule: no mocks for internal collaborators. If the code under test is hard to test as written, the agent must say so and recommend `/refactor` rather than mock around the design.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Since `/test` always adds test files to the codebase, Mode A always applies here.
