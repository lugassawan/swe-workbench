# Plan Workflow Section Template

Copy this `## Workflow` section into your plan and substitute `<detected ...>` placeholders with actual values from Project Detection.

---

````markdown
## Workflow

### Phase 1: Branch
- **Convention:** `<detected pattern, e.g., feature/description, fix/JIRA-123-description>`
- **Create:** `git checkout -b <branch-name>` (or worktree via `superpowers:using-git-worktrees`)

### Phase 2: Implement
- Follow plan tasks using `superpowers:executing-plans` or `superpowers:subagent-driven-development`
- Apply `superpowers:test-driven-development` per unit of work

### Phase 3: Verify

Run in order — stop on first failure, fix, re-run from format:

| Step | Command | Expected |
|------|---------|----------|
| Format | `<detected command>` | Clean |
| Lint | `<detected command>` | 0 issues |
| Test | `<detected command>` | All pass |

After all pass, state with evidence:
```
Format: <command> — clean
Lint: <command> — 0 issues
Test: <command> — N/N pass
```

> **Sub-skill:** `superpowers:verification-before-completion`

### Phase 4: Review

Dispatch both reviewers:
- `superpowers:code-reviewer` — plan-alignment, standards
- `swe-workbench:reviewer` subagent — diff correctness/security/design in `Severity | File:Line | Issue | Why it matters | Suggested fix` format

Act on feedback:
- **Critical/Important:** fix → re-verify → re-review
- **Minor:** note or fix inline

> **Sub-skill:** `superpowers:requesting-code-review`

### Phase 5: Deliver

**Commit convention:** `<detected style, e.g., "feat: description" or "[feat] description">`

**PR template:** `<detected template path, or "none — use default format">`

If a PR template exists, use it and fill in every section. Otherwise:

```bash
git push -u origin <branch-name>
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-3 bullets>

## Test Plan
- [ ] <verification steps>
EOF
)"
```

> **Sub-skill:** `superpowers:finishing-a-development-branch`
````
