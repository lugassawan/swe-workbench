# Deferred-verification follow-up — filing mechanics

Detail for `SKILL.md` Step 8. Runs only after Steps 3–6 have already completed unconditionally —
this step never gates or delays cleanup, and it never files or branches without explicit
confirmation.

## Gate

The `body` fetched in Step 1/2 (or Step 2's re-fetch, whichever ran last) contains the exact line:

```
<!-- swe-workbench:deferred-verification -->
```

`/swe-workbench:hotfix` writes this marker when a PR ships ahead of its regression test
(verification deferred by design) and strips it once the debt is paid. If the marker is absent,
Step 8 is a silent no-op — do not print anything about it, and leave the Step 7 report at four
lines.

## Offer

```json
{
  "questions": [{
    "question": "This merged PR shipped with deferred verification (hotfix). How should the regression-test debt be tracked?",
    "header": "Deferred debt",
    "multiSelect": false,
    "options": [
      { "label": "File a follow-up issue", "description": "Preview + confirm gate, then gh issue create — mirrors workflow-audit-emit-issues." },
      { "label": "Create a test branch",   "description": "git checkout -b test/<slug> off the freshly-synced default branch from Step 3." },
      { "label": "Skip",                    "description": "No follow-up. The marker's debt is left untracked beyond this report." }
    ]
  }]
}
```

## File a follow-up issue

1. Derive `<slug>` from the merged PR's `headRefName` (strip the `hotfix/` prefix).
2. Body schema:
   ```markdown
   ## Backfill regression test — hotfix PR #<number>

   Hotfix PR #<number> (`<headRefName>`) shipped with deferred verification: the fix landed
   without a regression test, tracked via the `<!-- swe-workbench:deferred-verification -->`
   marker on the PR body.

   ### Scope
   - [ ] Add a regression test that fails without the fix and passes with it.
   - [ ] Confirm `superpowers:verification-before-completion` is green with that test included.
   - [ ] Reassess whether the original hotfix needs a more proper implementation now that time
         pressure is off.

   ## Provenance
   Filed by `workflow-cleanup-merged` Step 8 after merge of #<number>.
   ```
3. Label discovery: `gh label list --json name -q '.[].name'`; prefer a label matching `test` or
   `tech-debt` (case-insensitive substring), else omit `--label`.
4. Write the body to `/tmp/cleanup-followup-<number>.md` (Write tool) and a `.cmd` sidecar holding
   the exact `gh issue create --title "Backfill regression test — hotfix PR #<number>" --body-file
   <path> [--label <label>]` line. Print the preview; **wait for the literal `confirm` reply** —
   never file before it.
5. On `confirm`: run the sidecar command, return the issue URL, then reap both temp files via
   `runtime/clean-state-files.sh` (same pattern as `workflow-audit-emit-issues` Phase 4).

## Create a test branch

```bash
git checkout -b "test/<slug>"
```

Off the default branch already synced in Step 3 — no new sync needed. Report the branch name; do
not push it or open a PR (that is a separate, later action the user drives).

## Skip

No action. Note "skipped" in the Step 7 report's 5th line.

## Common mistakes

| Mistake | Fix |
|---|---|
| Running Step 8 before Steps 3–6 finish | Never — the marker check and offer always come last. |
| Filing the issue without the `confirm` gate | Preview first, always. Same discipline as `workflow-audit-emit-issues`. |
| Treating marker-absent as an error | It's the common case — most merges never had deferred verification. Silent no-op. |
| Re-syncing the default branch for the test-branch option | Step 3 already synced it this run — reuse, don't re-fetch. |
