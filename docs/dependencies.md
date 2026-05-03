# Runtime dependencies

`swe-workbench` composes with other Claude Code plugins at runtime:

| Plugin | Source | Used for | Required? |
|---|---|---|---|
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) | **Skills** (invoked via Skill tool from `skills/workflow-development/`, `commands/implement.md`, `agents/debugger.md`): `using-git-worktrees`, `executing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`, `systematic-debugging`, `writing-plans`.<br>**Subagent** (dispatched via `subagent_type` from `skills/workflow-development/`): `code-reviewer`. | Required for the `workflow-development` skill to function end-to-end. |
| `claude-plugins-official` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Official Anthropic plugin collection — install if you need any of its bundled tools. | Optional. |

Install them via `/plugin marketplace add …` + `/plugin install …` before using the `workflow-development` skill.
