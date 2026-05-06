# Runtime dependencies

`swe-workbench` composes with other Claude Code plugins at runtime:

| Plugin | Source | Used for | Required? |
|---|---|---|---|
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) | Skills invoked via Skill tool (from `skills/workflow-development/`, `commands/implement.md`, `agents/debugger.md`): `using-git-worktrees` (fallback when rimba is absent), `executing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`, `systematic-debugging`, `writing-plans`, `code-reviewer`. | Required for the `workflow-development` skill to function end-to-end. |
| `rimba` | [lugassawan/rimba](https://github.com/lugassawan/rimba) | Optional worktree-lifecycle provider. When available (on PATH or at `~/.local/bin/rimba`, `~/go/bin/rimba`), `workflow-development` Phase 1 uses `rimba add <task>` instead of `superpowers:using-git-worktrees`, and `workflow-cleanup-merged` uses `rimba remove <task>` instead of raw `git worktree` shell commands. Ships a built-in MCP server (`rimba mcp`) for AI-tool integration. Install: `go install github.com/lugassawan/rimba@latest` or download from the releases page. | Optional. Falls back to `superpowers:using-git-worktrees` / `git worktree` when absent. |
| `claude-plugins-official` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Official Anthropic plugin collection — install if you need any of its bundled tools. | Optional. |

Install them via `/plugin marketplace add …` + `/plugin install …` before using the `workflow-development` skill.

## Claude Code native tools

The following tools are built into Claude Code itself — no plugin install required:

| Tool | Used for | Notes |
|---|---|---|
| `EnterWorktree(name=…)` | Creates a new worktree (if the name doesn't already exist) and enters it — moves the session CWD without restart. Use `superpowers:using-git-worktrees` as the safe wrapper: it handles consent, `.gitignore` checks, and baseline tests before calling this. | Built into Claude Code; no install needed. Verify with `claude --version`. |
| `EnterWorktree(path=…)` | Enters an existing worktree by absolute path (path must appear in `git worktree list`). Used directly by `workflow-worktree-session` for mid-session switches. | same |
| `ExitWorktree(action: "keep"\|"remove")` | Returns the session to the main worktree. `"remove"` deletes the linked worktree dir; `"keep"` leaves it on disk. | same |

These are the tools `workflow-worktree-session` routes to. If a tool is not found, your Claude Code version may predate its introduction — run `claude --version` and update if needed.
