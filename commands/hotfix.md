---
description: Ship a fast branch-based P0 hotfix — diagnose, implement, open a ready-for-review PR, then verify + review after (deferred by design)
argument-hint: <ticket ref, GitHub issue URL, or symptom> [--grill | --standard]
---

Hotfix request: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.

Activate the `swe-workbench:workflow-hotfix` skill. It owns the reordered lifecycle — a plain branch (never a worktree), a minimal fix with TDD relaxed, a ready-for-review PR opened *before* verification and review, then verify + review running against the open PR, then a reconcile step that strips the deferred-verification marker only if the regression test was backfilled and verification is green.

Absolute rules:
- Always branch, never worktree — `git checkout -b hotfix/<slug>` off the synced default branch. This command exists specifically to skip worktree ceremony.
- Always open the PR ready-for-review, never draft — speed is the point.
- Verification and review always run *after* the PR is opened, never before — this command's entire identity is deferred verification. Do not reorder to verify-then-PR; that is `/swe-workbench:implement`.
- Write the deferred-verification marker (`<!-- swe-workbench:deferred-verification -->`) into the PR body at open time. Strip it only if the regression test is backfilled AND verification is green, before requesting merge — never strip it preemptively.
- If the ticket lacks acceptance criteria, stop and ask the user — do not invent scope, even under time pressure.
- Do not invent architectural answers — escalate any genuine design fork to `senior-engineer`.
