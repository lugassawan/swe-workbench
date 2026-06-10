---
description: Invoke the test-writer subagent to add focused, behavioural tests in the target language's idiom. Pass --mode e2e (or --e2e) to run the browser-driven E2E pipeline instead.
argument-hint: <file, function, or module> [--mode e2e | --e2e]
---

Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

## Mode resolution

Parse `$ARGUMENTS` for `--mode e2e` or `--e2e`:

- **E2E mode** (`--mode e2e` or `--e2e` present): strip the flag from the target and follow the **E2E path** below.
- **Default mode** (no flag): follow the **Unit path** below.

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

## Unit path (default)

Delegate to the `test-writer` subagent. Its output must include:

1. **Behaviour inventory** — numbered list of all behaviours identified.
2. **Test file location and naming** — where the new tests live.
3. **Tests written** — count and names.
4. **Run result** — command used and pass / fail summary.
5. **Untested behaviours and why** — e.g., "covered by integration test", "trivial getter".

Absolute rule: no mocks for internal collaborators. If the code under test is hard to test as written, the agent must say so and recommend `/refactor` rather than mock around the design.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Since `/test` always adds test files to the codebase, Mode A always applies here.
