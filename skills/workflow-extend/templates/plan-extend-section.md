# Plan Extend Section Template

Copy this `## Workflow` section into your extend spec and substitute `[[detect:KEY]]` markers with actual values from Project Detection.

> Reuses existing branch `[[detect:branch-name]]` and updates PR [[detect:pr-url]] (#[[detect:pr-number]]). No new branch, no new PR.

---

````markdown
## Workflow

> **Extend mode:** Reuses existing branch `[[detect:branch-name]]` and updates PR [[detect:pr-url]].
> Phase 1 (Branch) is intentionally skipped — no new branch or worktree is created.

### Phase 2: Implement
- Follow plan tasks using `superpowers:executing-plans` or `superpowers:subagent-driven-development`
- Apply `swe-workbench:principle-tdd` per unit of work
- `skip-phase-1: existing branch [[detect:branch-name]] reused from open PR #[[detect:pr-number]]`

### Phase 3: Verify

Run in order — stop on first failure, fix, re-run from format:

| Step | Command | Expected |
|------|---------|----------|
| Format | `[[detect:format-command]]` | Clean |
| Lint | `[[detect:lint-command]]` | 0 issues |
| Test | `[[detect:test-command]]` | All pass |

After all pass, state with evidence:
```
Format: [[detect:format-command]] — clean
Lint: [[detect:lint-command]] — 0 issues
Test: [[detect:test-command]] — N/N pass
```

> **Sub-skill:** `superpowers:verification-before-completion`

### Phase 4: Review

Dispatch both reviewers:
- `superpowers:code-reviewer` — plan-alignment, standards
- `swe-workbench:reviewer` subagent — diff correctness/security/design in `Severity | File:Line | Issue | Why it matters | Suggested fix` format

Reviewer **additional check:** does the diff scope match the captured AC? Flag scope creep as `Severity: High | scope-creep | <files>` before proceeding.

Act on feedback:
- **Critical/Important:** fix → re-verify → re-review
- **Minor:** note or fix inline

### Phase 5: Deliver

**Commit convention:** `[[detect:commit-style]]`

**Commit format:** `[<type>] sub-idea: <one-line restatement>`

**Commit body must include:** `Ref: extend-[[detect:extend-ts]]` (substitute `[[detect:extend-ts]]` with the actual timestamp from Phase A's `date +%s` call)

**Delivery path:** Update existing PR #[[detect:pr-number]] — **never** run `gh pr create`.

```bash
git push -u origin [[detect:branch-name]]
# workflow-commit-and-pr "Update existing PR" path handles the rest
```

> **Sub-skill:** `swe-workbench:workflow-commit-and-pr` → choose "Update existing PR"
````
