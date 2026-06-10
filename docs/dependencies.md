# Runtime dependencies

`swe-workbench` composes with other Claude Code plugins at runtime:

| Plugin | Source | Used for | Required? |
|---|---|---|---|
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) | Skills invoked via Skill tool (from `skills/workflow-development/`, `commands/implement.md`, `agents/debugger.md`): `using-git-worktrees` (fallback when rimba is absent), `executing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`, `systematic-debugging`, `writing-plans`. | Required for the `workflow-development` skill to function end-to-end. |
| `rimba` | [lugassawan/rimba](https://github.com/lugassawan/rimba) | Optional worktree-lifecycle provider. When available (on PATH or at `~/.local/bin/rimba`, `~/go/bin/rimba`), `workflow-development` Phase 1 uses `rimba add <task>` instead of `superpowers:using-git-worktrees`, and `workflow-cleanup-merged` uses `rimba remove <task>` instead of raw `git worktree` shell commands. Ships a built-in MCP server (`rimba mcp`) for AI-tool integration. Install: `go install github.com/lugassawan/rimba@latest` or download from the releases page. | Optional. Falls back to `superpowers:using-git-worktrees` / `git worktree` when absent. |
| `claude-plugins-official` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Official Anthropic plugin collection — install if you need any of its bundled tools. | Optional. |

Install them via `/plugin marketplace add …` + `/plugin install …` before using the `workflow-development` skill.

## Browser automation (optional, feature-gated)

The following MCP servers enable browser-driven E2E testing and console/network diagnostics. All three are **optional** and **hard-gated**: if the required server is absent when a browser feature is invoked, the command returns a `BLOCKED:` message with a per-backend install hint rather than silently degrading.

| Server | Source | Used by | Install | Required? |
|---|---|---|---|---|
| Playwright MCP | [`microsoft/playwright-mcp`](https://github.com/microsoft/playwright-mcp) | `/test --mode e2e` — browser snapshot → interact → assert spec authoring via `e2e-test-writer` | `npx @playwright/mcp@latest` | Required **only** for `/test --mode e2e` (hard-gated: absent → `BLOCKED:`) |
| Chrome DevTools MCP | [`ChromeDevTools/chrome-devtools-mcp`](https://github.com/ChromeDevTools/chrome-devtools-mcp) | `/debug` console/network/perf diagnostics for web-UI symptoms via `read_console_messages` + `read_network_requests` | `npx chrome-devtools-mcp@latest` | Optional; one Chrome backend required for `/debug` browser diagnostics (hard-gated) |
| Claude-in-Chrome | In-harness (`mcp__claude-in-chrome__*`) | `/debug` console/network capture when the Claude browser extension is connected — alternative to chrome-devtools-mcp | None (provided by the Claude Code harness) | Optional alternative to chrome-devtools-mcp for `/debug` browser diagnostics |

**Gate behaviour:** when a browser feature is invoked and the required server is absent, the command returns `BLOCKED: … install with \`npx <server>@latest\` …` and stops. It does not fall back silently or produce partial results. Non-browser `/test` (unit) and non-web-UI `/debug` are completely unaffected by these servers.

**`hangwin/mcp-chrome` — evaluated and not adopted:** this server is oriented toward semantic page search and content extraction; it does not provide the deterministic console/network capture (`read_console_messages`, `read_network_requests`) or E2E interaction primitives needed here. `chrome-devtools-mcp` and Claude-in-Chrome provide the right primitives for `/debug`; Playwright MCP provides the right primitives for `/test --mode e2e`.

## Claude Code native tools

The following tools are built into Claude Code itself — no plugin install required:

| Tool | Used for | Notes |
|---|---|---|
| `EnterWorktree(name=…)` | Creates a new worktree (if the name doesn't already exist) and enters it — moves the session CWD without restart. Use `superpowers:using-git-worktrees` as the safe wrapper: it handles consent, `.gitignore` checks, and baseline tests before calling this. | Built into Claude Code; no install needed. Verify with `claude --version`. |
| `EnterWorktree(path=…)` | Enters an existing worktree by absolute path (path must appear in `git worktree list`). Used directly by `workflow-worktree-session` for mid-session switches. | same |
| `ExitWorktree(action: "keep"\|"remove")` | Returns the session to the main worktree. `"remove"` deletes the linked worktree dir; `"keep"` leaves it on disk. | same |

These are the tools `workflow-worktree-session` routes to. If a tool is not found, your Claude Code version may predate its introduction — run `claude --version` and update if needed.
