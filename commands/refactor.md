---
description: Invoke the refactorer subagent for a behavior-preserving refactor, or a preview-gated dead-code removal with --dead-code
argument-hint: <file, function, or module> | --dead-code [path]
---

<!-- swb-phase: plan -->

Target: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

## Dead-code mode (`--dead-code [path]`)

If `$ARGUMENTS` begins with `--dead-code` (optionally followed by a path), run this two-pass flow instead of the default delegation. The main loop owns the confirm gate — the subagent cannot ask questions.

1. **Scan.** Run `bin/swe-workbench-dead-code-scan --root "$(git rev-parse --show-toplevel)" --funnel auto` via `Bash` and capture the JSON envelope — always the whole repo, never the `[path]` subtree, so references from sibling packages still count and candidate paths stay repo-relative. When `[path]` was given, keep only the `candidates[]` whose `path` falls under it (a prefix filter applied here in the main loop). On a non-zero exit or unparsable stdout, stop and report. If `warnings` carries a `file-cap` entry the index was truncated and "unused" claims are unsound: report the candidates with that caveat and stop — never offer removal.
2. **Preview pass.** Delegate the envelope to the `swe-workbench:refactorer` subagent (dead-code preview): it applies judgment — reclassifying candidates whose `note` genuinely justifies keeping as "justified — kept", verifying references of `detected_by: "grep"` candidates before confirming them — and returns a preview table (Symbol | Kind | File:Line | Class | Evidence) plus its recommended removal list.
3. **Confirm gate.** In the main loop, present the preview table and ask via `AskUserQuestion`: "Remove N confirmed candidates (one commit per symbol on the current branch)?" — options: **Remove all confirmed** (recommended), **Remove a subset** (user names the symbols), **Abort**. Rows classified safe-keep or justified are shown for information and are never offered for removal.
4. **Removal pass.** Refuse to start on the repository's default branch — tell the user to switch to a feature branch first. For each confirmed symbol, in envelope order: delegate to the `swe-workbench:refactorer` (dead-code removal, one symbol) — remove the symbol and the tests that only exercise it — then run the target repo's test suite. Green → commit that symbol alone through `swe-workbench:workflow-commit-and-pr` in commit-only mode (so the target repo's commit convention applies; never push), then re-run the scan as a drift-guard: a still-confirmed symbol whose `keep_class` or evidence changed pauses for re-confirmation; newly surfaced candidates (cascade orphans) render a new preview and go back to the confirm gate — they never chain automatically. Red → discard that symbol's uncommitted edits (restore the files the removal touched; earlier symbols' commits stay) and mark it "kept — tests failed".
5. **Report.** Removed (with one commit hash per symbol), kept — tests failed, justified — kept, safe-kept, and any drift pauses.

Absolute rules carry over: no feature changes; safe-keep and justified symbols are never removed; a removal that alters public behavior is a stop-and-report, not a fix-forward.

## Default delegation

Delegate to the `swe-workbench:refactorer` subagent. Its output must include:

1. **Diagnosis** — which smell is present (Long Method, Feature Envy, Primitive Obsession, Shotgun Surgery, Divergent Change, etc.) and why it hurts.
2. **Target state** — the shape of the code after refactoring, referenced to Fowler's catalog.
3. **Step plan** — ordered steps, each behavior-preserving and independently testable, each named from the catalog (Extract Function, Move Function, Replace Conditional with Polymorphism, Introduce Parameter Object…).
4. **Verification** — which tests protect each step; write characterization tests first if coverage is missing.

Absolute rule: no feature changes during refactoring.

**Plan output:** If you (the orchestrator) author a plan based on the subagent's response **and that plan modifies the codebase** (fix / make / implement) — whether saved to a plan file or passed to `ExitPlanMode` — first activate `swe-workbench:workflow-development` in **Mode A** and embed the rendered `## Workflow` section in the plan per `skills/workflow-development/templates/plan-workflow-section.md`. Run the skill's project-detection (`git branch -a`, `git log --oneline -20`, Makefile grep, PR-template lookup) so the placeholders are substituted from this repo, not left as `[[detect:…]]`. Skip Mode A if the plan is pure analysis, design recommendation, or any output that does not introduce file edits — the Workflow section's phases (Branch / Verify / Deliver) do not apply.
