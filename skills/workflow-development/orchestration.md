# Mode C — Multi-Issue Orchestration

For dispatching individual agents and agent prompt structure, see `superpowers:dispatching-parallel-agents` and `superpowers:subagent-driven-development`. This file covers the **multi-PR campaign layer**: managing dependency rounds, post-merge state, and worktree cleanup between rounds.

**Three principles:**
1. Orchestrator stays on main — all code work goes to worktree-isolated agents
2. Maximize parallelism — spawn all unblocked issues simultaneously, not in batches of 3
3. CI is the gatekeeper — every PR must have CI passing before presenting to user for merge

## Round Lifecycle

```
┌─ 1. SELECT: Map dependency graph → identify all currently unblocked issues
│
├─ 2. SPAWN: Launch worktree-isolated agents for each unblocked issue
│   └─ Each agent: branch → implement → verify → review → PR → verify CI
│
├─ 3. MONITOR: Check CI status on all open PRs
│   └─ CI fails → spawn worktree-isolated fix agent for that PR
│
├─ 4. PRESENT: Report all PRs with CI status to user
│   └─ Note merge order if PRs touch shared files
│
├─ 5. MERGE: User merges PRs (in noted order)
│
├─ 6. SYNC: git pull on main
│   └─ gh pr view --json mergeable on remaining open PRs
│   └─ Spawn fix agents for any conflicting PRs
│
├─ 7. CLEANUP: For each merged PR → invoke `swe-workbench:workflow-cleanup-merged`
│   └─ Skill handles: gh-verified merge check, worktree removal, local + remote branch deletion
│
└─ 8. NEXT ROUND: Back to step 1 — re-evaluate dependency graph
```

## Conflict Prevention

- **Pre-create shared file stubs** (Makefile targets, constants files) before spawning parallel agents that will modify them
- **Note merge order** when multiple PRs touch the same files
- **Use `--body-file`** instead of heredocs when creating GitHub issues or PRs with code-heavy content — shell `$()` breaks on `)` in code blocks

## Common Orchestration Mistakes

| Mistake | Fix |
|---------|-----|
| Orchestrator checks out a branch | Never. Stay on main. Spawn a worktree agent. |
| Spawn only 3 agents when 8 are unblocked | Spawn all unblocked agents. Maximize throughput. |
| Wait for batch 1 to merge before spawning remaining unblocked issues | If unblocked issues remain, spawn them immediately. |
| Skip CI verification on PR | Always run `gh pr checks`. CI failures caught early prevent merge issues. |
| Don't clean up worktrees after merge | Invoke `swe-workbench:workflow-cleanup-merged` after each merge round — it handles gh-verified merge check, worktree removal, and local + remote branch deletion safely. |
| Ignore merge conflicts on remaining PRs after a merge | Always check `gh pr view --json mergeable` after each merge round. |
| Use heredocs for PR bodies with code | Use `--body-file` with temp files. |
