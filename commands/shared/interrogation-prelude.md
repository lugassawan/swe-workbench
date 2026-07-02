**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.
