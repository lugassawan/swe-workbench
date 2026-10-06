---
description: Consult the senior-engineer subagent for an architectural decision
argument-hint: <design question> [--pr [N]] [--new-pr] [--grill | --standard]
---

<!-- swb-phase: plan -->

The user is asking: $ARGUMENTS

If $ARGUMENTS contains `--pr` or `--new-pr`, skip the next two steps (ticket-context and interrogation mode) and go straight to **PR redesign** below.

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.

**PR redesign (`--pr`).** If $ARGUMENTS contains `--new-pr` without `--pr`, print "`--new-pr` requires `--pr`" and stop. If it contains `--pr`, the ticket-context and interrogation-mode steps above are skipped (see the `--pr` guard at the top): run neither here, and skip the delegation below and the "Plan output" paragraph. The question is a request to re-plan an open PR's approach rather than a fresh design. Parse `--pr [N]`: N is the next token only when it matches `^#?[0-9]+$` (strip the `#`); otherwise it is absent and the current branch's PR is used after confirmation, and that token belongs to the reason. A `#N` operand of `--pr` is a PR number, not a ticket reference. Also parse `--new-pr`, any explicit mode signal as `MODE` (the same ones the interrogation-mode step honors: `--grill`, "grill me", "grill-me mode", `--standard`, "standard", "quick" — strip it from `WHY`), and the remaining free text as `WHY`. Activate `swe-workbench:workflow-redesign` and pass it `PR_ARG`, `WHY`, `NEW_PR` and `MODE`. The skill owns the ownership gate, mode resolution (after that gate, so a refused PR never starts a grill loop), both approval gates and the whole rebuild lifecycle; run nothing else from this command.

Otherwise, delegate to the `swe-workbench:senior-engineer` subagent. Its response must contain:

1. **Problem restatement** — confirm the real question and surface implicit constraints (scale, team size, change frequency, latency budget, compliance).
2. **Options** — 2–3 candidate approaches, each with sketch, strengths, weaknesses, and reversibility.
3. **Recommendation** — one option chosen, reasoned against Clean Architecture's dependency rule and DDD boundaries where relevant.
4. **Risks** — what could make this choice wrong, and which signals to watch.

If the question is under-specified, the subagent asks clarifying questions before recommending. Call out YAGNI explicitly when the design is premature.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
