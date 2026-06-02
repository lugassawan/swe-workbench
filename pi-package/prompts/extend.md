---
description: Capture a mid-PR sub-idea and implement it onto the current open PR's branch — no new branch, no new PR. Preserves Verify → Review → Deliver.
argument-hint: <one-line sub-idea> [--grill | --standard]
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
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
