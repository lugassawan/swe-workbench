# Plan Workflow Section Template

Copy this `## Workflow` section into your plan **in full — do not abridge, summarize, or collapse steps.** Substitute `[[detect:KEY]]` markers with actual values from Project Detection; that substitution is the only permitted edit.

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
- **Monorepo scope:** prefix the task with the service/package name — `rimba add <service>/<task> [--flag]` → `<prefix>/<service>/<task>` (e.g. `rimba add backend-api/auth-redirect --bugfix` → `bugfix/backend-api/auth-redirect`). For cross-cutting changes, pick the service where most file edits land; if two services tie, prefer the service that owns the primary interface changed; omit scope only if no service file is touched at all.
- **Post-create timing:** `rimba add` installs deps and runs `post_create` hooks after creating the worktree. `Path:` is printed **before deps** install begins — coding may start as soon as `Path:` appears, but wait for `rimba add` to fully complete before running tests. Only pass `--skip-deps`/`--skip-hooks` when the test suite genuinely needs no installation step; never skip and reinstall manually.
- **Reclaim install time:** on a long install, background the `rimba add` call so the session is free. Enter the worktree once `Path: <abs-path>` appears and implement immediately. When rimba finishes, reconcile TDD: `git stash` the implementation → write failing test → run (**RED**) → `git stash pop` → run (**GREEN**). Skip when install is fast or `post_create` hooks rewrite files you'd edit.
- **Enter worktree:** Try `EnterWorktree path=<rimba-output-path>` first — this works from the main session for any git-registered worktree (including rimba's `../<repo>-worktrees/` layout). If rejected for any reason (most commonly: session already inside a worktree with the path outside `.claude/worktrees/`), fall back to `cd <rimba-output-path>` via Bash; note that `cd` only anchors the Bash persistent cwd and does not re-anchor session-level caches the way `EnterWorktree` does.
- **Resume note:** record the worktree path (`Path:` line from `rimba add`) in the plan. On any continued or resumed session, try `EnterWorktree path=<that-path>` first; if rejected, re-`cd <that-path>` (Bash cwd resets on session resume). If you catch yourself cd-prefixing commands, that is the signal to stop and try `EnterWorktree path=<worktree-path>` — if it is rejected, the cd-prefix is the sanctioned fallback.
- **Exit (cd-fallback sessions):** if uncertain whether the worktree was entered via `EnterWorktree` or `cd`, attempt `ExitWorktree(action=keep)` first; if it reports a no-op, return to main with `_GCD=$(git rev-parse --git-common-dir); [[ "$_GCD" != /* ]] || cd "${_GCD%/.git}"`. See `workflow-worktree-session` Mode C for the full exit contract.
- **Promote existing work:** if the change is already underway on the current branch (not the default branch), `rimba add branch:<current-branch>` promotes it into a worktree (moves dirty state via stash) instead of creating a fresh branch.
- **Fallback only when rimba is absent:** invoke `superpowers:using-git-worktrees`. Do NOT invoke it when rimba is available — its Step 1a guidance steers toward `EnterWorktree name=…`, which mangles branch names containing `/` (e.g. `feature/101-foo` → `worktree-feature+101-foo`).
- **If `rimba add` fails** (non-zero exit): report the error verbatim and ask the user whether to retry or fall back to `superpowers:using-git-worktrees`. Do not silently swallow the error.

### Phase 2: Implement
- Follow plan tasks using `superpowers:executing-plans` or `superpowers:subagent-driven-development`
- Apply `swe-workbench:principle-tdd` per unit of work

### Phase 3: Verify

Run in order — stop on first failure, fix, re-run from imports (or invoke `superpowers:verification-before-completion` which handles the loop):

| Step    | Command                      | Expected |
|---------|------------------------------|----------|
| Imports | `[[detect:imports-command]]` | Clean    |
| Format  | `[[detect:format-command]]`  | Clean    |
| Quality | `[[detect:quality-command]]` | Within thresholds (or "not configured — skipped") |
| Lint    | `[[detect:lint-command]]`    | 0 issues |
| Test    | `[[detect:test-command]]`    | All pass |

After all pass, state with evidence:
```
Imports: [[detect:imports-command]] — clean
Format: [[detect:format-command]] — clean
Quality: [[detect:quality-command]] — within thresholds (or "not configured — skipped")
Lint: [[detect:lint-command]] — 0 issues
Test: [[detect:test-command]] — N/N pass
```

> **Sub-skill:** `superpowers:verification-before-completion`

### Phase 4: Review

Dispatch both reviewers:
- `superpowers:requesting-code-review` — plan-alignment, standards
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
