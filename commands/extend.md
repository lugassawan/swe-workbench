---
description: Capture a mid-PR sub-idea and implement it onto the current open PR's branch — no new branch, no new PR. Preserves Verify → Review → Deliver.
argument-hint: <one-line sub-idea> [--grill | --standard]
---

Sub-idea: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the delegation context below. Skip if $ARGUMENTS is free-text with no recognizable ref. (Trigger patterns are defined in that skill's "When to invoke" section.)

**PR detection (inline):**

```bash
PR_JSON=$(gh pr view --json number,state,headRefName,isDraft,url 2>/dev/null || true)
PR_STATE=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || true)
PR_NUM=$(echo "$PR_JSON"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('number',''))" 2>/dev/null || true)
HEAD_REF=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('headRefName',''))" 2>/dev/null || true)
PR_URL=$(echo "$PR_JSON"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('url',''))" 2>/dev/null || true)
IS_DRAFT=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('isDraft') else 'false')" 2>/dev/null || true)
```

Note: `gh pr view` resolves against `origin`; on fork-based workflows where `origin` is the fork, it may return no PR. If that happens, use `gh pr view --repo <upstream-owner>/<repo>` explicitly.

If `PR_STATE` is `"OPEN"`: capture PR_NUM, HEAD_REF, PR_URL, and IS_DRAFT into context. If `IS_DRAFT` is `"true"`, note "Draft PR detected — it will not be auto-marked ready-for-review." Before activating `workflow-extend`, complete the following interrogation step (OPEN branch only):

**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.

Then activate `swe-workbench:workflow-extend` with all four values.

The list below is a visible contract of the phases `workflow-extend` runs — it does **not** replace the skill activation above. Execute phases 2–5 in order. **Phase 1 (Branch) is intentionally skipped** — the open PR branch is reused, so no new branch or worktree is created.

**Phase 2 — Implement**
Execute the plan via `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Apply `swe-workbench:principle-tdd` per unit: red → green → refactor.

**Phase 3 — Verify**
Run `superpowers:verification-before-completion` before claiming any phase done. Do not advance to Phase 4 until format / lint / test pass with evidence.

**Phase 4 — Review**
Dispatch **BOTH** reviewers **IN PARALLEL** — in a single batch (same turn), as two distinct required invocations, **neither optional**:
- `superpowers:requesting-code-review` (a **Skill**) — plan-alignment, standards
- `swe-workbench:reviewer` (a **subagent**) — diff correctness/security/design in `Severity | File:Line | Issue | Why it matters | Suggested fix` format

Running the Skill inline and skipping the `swe-workbench:reviewer` subagent (or vice-versa) does **not** satisfy this phase. Do not advance to Phase 5 until review passes clean or all raised issues are resolved.

**Phase 5 — Deliver**
Invoke `swe-workbench:workflow-commit-and-pr` to update the **existing** PR — never `gh pr create`, never a second PR.

If `PR_STATE` is not `"OPEN"` (empty, `"CLOSED"`, `"MERGED"`, or `gh` error): surface the following `AskUserQuestion` and **return** — do **not** activate `workflow-extend`:

```json
{
  "questions": [{
    "question": "No open PR found for the current branch. How would you like to proceed?",
    "header": "No open PR",
    "multiSelect": false,
    "options": [
      {
        "label": "Open a PR first",
        "description": "Commit and push current work, open a PR, then re-run /extend."
      },
      {
        "label": "Defer to /capture + /implement",
        "description": "File a new top-level issue via /capture, then implement it on a new branch via /implement."
      },
      {
        "label": "Abort",
        "description": "Exit without any changes."
      }
    ]
  }]
}
```

Absolute rules:
- Never create a new branch or worktree.
- Never call `gh pr create` when an open PR exists for this branch.
- Never create a second PR — the only delivery path is updating the existing PR.
- Escalate to `senior-engineer` only on explicit user opt-in ("consult senior-engineer" / "this is architectural").
- Do not skip Phase 3 (Verify) or Phase 4 (Review) under any circumstances.
