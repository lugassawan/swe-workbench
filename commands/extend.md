---
description: Capture a mid-PR sub-idea and implement it onto the current open PR's branch — no new branch, no new PR. Preserves Verify → Review → Deliver.
argument-hint: <one-line sub-idea>
---

Sub-idea: $ARGUMENTS

If $ARGUMENTS contains a ticket reference, invoke `swe-workbench:ticket-context` first and prepend its structured summary to the context below. Skip if $ARGUMENTS is free-text with no recognizable ref.

**PR detection (inline):**

```bash
PR_JSON=$(gh pr view --json number,state,headRefName,isDraft,url 2>/dev/null || true)
PR_STATE=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || true)
PR_NUM=$(echo "$PR_JSON"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('number',''))" 2>/dev/null || true)
HEAD_REF=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('headRefName',''))" 2>/dev/null || true)
PR_URL=$(echo "$PR_JSON"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('url',''))" 2>/dev/null || true)
IS_DRAFT=$(echo "$PR_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('isDraft','false'))" 2>/dev/null || true)
```

If `PR_STATE` is `"OPEN"`: capture PR_NUM, HEAD_REF, PR_URL, and IS_DRAFT into context. If `IS_DRAFT` is `"True"`, note "Draft PR detected — it will not be auto-marked ready-for-review." Then activate `swe-workbench:workflow-extend` with all four values.

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
