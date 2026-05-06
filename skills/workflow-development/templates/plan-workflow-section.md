# Plan Workflow Section Template

Copy this `## Workflow` section into your plan and substitute `[[detect:KEY]]` markers with actual values from Project Detection.

---

````markdown
## Workflow

### Phase 1: Branch
- **Convention:** `[[detect:branch-convention]]`
- **Create:** `rimba add <task>` (if rimba on PATH / `~/.local/bin/rimba` / `~/go/bin/rimba`) — else `superpowers:using-git-worktrees`

### Phase 2: Implement
- Follow plan tasks using `superpowers:executing-plans` or `superpowers:subagent-driven-development`
- Apply `superpowers:test-driven-development` per unit of work

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

Act on feedback:
- **Critical/Important:** fix → re-verify → re-review
- **Minor:** note or fix inline

> **Sub-skill:** `superpowers:requesting-code-review`

### Phase 5: Deliver

**Commit convention:** `[[detect:commit-style]]`

**PR template:** `[[detect:pr-template-path]]`

If a PR template was detected (recorded in Project Detection), use it:

```bash
git push -u origin <branch-name>
gh pr create --title "<title>" --body-file "[[detect:pr-template-path]]"
```

Before invoking, replace the `Closes #` placeholder with the resolved issue ref (`Closes #123`) or a standalone `Issue: N/A — <reason>` line. Never leave `Closes #` empty.

If **no** template was found, use the heredoc fallback:

```bash
git push -u origin <branch-name>
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
<2-3 bullets>

## Test Plan
- [ ] <verification steps>

<!-- If your repo requires an issue reference, add it per CONTRIBUTING.md or PR template; if none, use a standalone "Issue: N/A — <reason>" line. -->
EOF
)"
```

> **Sub-skill:** `superpowers:finishing-a-development-branch`
````
