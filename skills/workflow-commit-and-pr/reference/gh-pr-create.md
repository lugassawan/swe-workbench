# gh pr create pre-flight reference

Detailed steps for the two pre-flight gates that run before `gh pr create`.

## Pre-check: existing PR for this branch

Before running `gh pr create`, check whether an OPEN PR already exists for this branch:

```bash
PR_INFO=$(gh pr view --json url,state -q '.state + "\t" + .url' 2>/dev/null || true)
PR_STATE=$(echo "$PR_INFO" | cut -f1)
PR_URL=$(echo "$PR_INFO"   | cut -f2)
```

Filter: act only when `PR_STATE == "OPEN"`. Ignore `CLOSED` or `MERGED` PRs — those do not block new-PR creation.

If an OPEN PR is found, call `AskUserQuestion` with:

```json
{
  "questions": [{
    "question": "An open PR already exists for this branch. Update it or cancel?",
    "header": "Existing PR",
    "multiSelect": false,
    "options": [
      { "label": "Update existing PR", "description": "New commits are already on the branch — skip gh pr create and use the existing PR URL." },
      { "label": "Cancel",             "description": "Abort the flow. No PR is created or modified." }
    ]
  }]
}
```

- **`Update existing PR`** → skip `gh pr create`. Use the existing PR URL in all output. Run the Post-create CTA (offer `/review`) against the existing PR number.
- **`Cancel`** → abort. Print the existing PR URL for reference.

If no OPEN PR is found → proceed to the `## Draft vs ready prompt` step normally.

## Draft vs ready prompt

Before running `gh pr create`, call the `AskUserQuestion` tool with:

```json
{
  "questions": [{
    "question": "Open this PR as draft or ready for review?",
    "header": "PR mode",
    "multiSelect": false,
    "options": [
      { "label": "Ready for review", "description": "Default; runs `gh pr create`" },
      { "label": "Draft",            "description": "Adds `--draft` flag; hides from reviewers" }
    ]
  }]
}
```

Map the `Draft` answer → append `--draft` to `gh pr create`. Any other
answer (including `Ready for review` and the free-text `Other` channel) →
no flag. If the user supplies an `Other` reply that signals abort/cancel,
stop and re-confirm before running `gh pr create`.
