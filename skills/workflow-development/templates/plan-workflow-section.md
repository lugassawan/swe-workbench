# Plan Workflow Section Template

Copy this `## Workflow` section into your plan and substitute `[[detect:KEY]]` markers with actual values from Project Detection.

---

````markdown
## Workflow

### Phase 1: Branch
- **Convention:** `[[detect:branch-convention]]`
- **Primary:** `rimba add [<service>/]<task> [--flag]` (check PATH, `~/.local/bin/rimba`, `~/go/bin/rimba`) — produces typed branch names; pick the flag that matches the commit-tag this change will carry:

  | Work type | rimba flag | Branch prefix | Commit-tag |
  |---|---|---|---|
  | New feature *(default)* | *(none)* | `feature/<task>` | `[feat]` |
  | Bug fix | `--bugfix` | `bugfix/<task>` | `[fix]` |
  | Hotfix | `--hotfix` | `hotfix/<task>` | `[hotfix]` |
  | Documentation | `--docs` | `docs/<task>` | `[docs]` |
  | Tests | `--test` | `test/<task>` | `[test]` |
  | Chore / tooling | `--chore` | `chore/<task>` | `[chore]` |

- **Picking the prefix:** derive from the commit-tag the change will carry (taxonomy lives in `workflow-commit-and-pr`). Example: a `[fix]` change → `rimba add <task> --bugfix`.
- **Monorepo scope:** prefix the task with the service/package name — `rimba add <service>/<task> [--flag]` → `<prefix>/<service>/<task>` (e.g. `rimba add backend-api/auth-redirect --bugfix` → `bugfix/backend-api/auth-redirect`). For cross-cutting changes, pick the service where most file edits land; omit the scope only if no service clearly dominates.
- **Post-create timing:** `rimba add` installs deps and runs `post_create` hooks after creating the worktree. TDD/red-first runs: pass `--skip-deps`/`--skip-hooks` and install deps yourself before the first test; otherwise wait for `Path: <abs-path>` output before moving to Phase 2.
- **Enter worktree:** `EnterWorktree path=<rimba-output-path>` (harness tool) to switch the session in, or `cd <path>` in shell.
- **Fallback only when rimba is absent:** invoke `superpowers:using-git-worktrees`. Do NOT invoke it when rimba is available — its Step 1a guidance steers toward `EnterWorktree name=…`, which mangles branch names containing `/` (e.g. `feature/101-foo` → `worktree-feature+101-foo`).
- **If `rimba add` fails** (non-zero exit): report the error verbatim and ask the user whether to retry or fall back to `superpowers:using-git-worktrees`. Do not silently swallow the error.

### Phase 2: Implement
- Follow plan tasks using `superpowers:executing-plans` or `superpowers:subagent-driven-development`
- Apply `swe-workbench:principle-tdd` per unit of work

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

> **Sub-skill:** `swe-workbench:workflow-commit-and-pr`
````
