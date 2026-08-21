# Runtime dependencies

`swe-workbench` composes with other Claude Code plugins at runtime:

| Plugin | Source | Used for | Required? |
|---|---|---|---|
| `superpowers` | [obra/superpowers](https://github.com/obra/superpowers) | Skills invoked via Skill tool (from `skills/workflow-development/`, `commands/implement.md`, `agents/debugger.md`): `using-git-worktrees` (fallback when rimba is absent), `executing-plans`, `subagent-driven-development`, `test-driven-development`, `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`, `systematic-debugging`, `writing-plans`. | Required for the `swe-workbench:workflow-development` skill to function end-to-end. |
| `rimba` | [lugassawan/rimba](https://github.com/lugassawan/rimba) | Optional worktree-lifecycle provider. When available (on PATH or at `~/.local/bin/rimba`, `~/go/bin/rimba`), `swe-workbench:workflow-development` Phase 1 uses `rimba add <task>` instead of `superpowers:using-git-worktrees`, and `swe-workbench:workflow-cleanup-merged` uses `rimba remove <task>` instead of raw `git worktree` shell commands. Ships a built-in MCP server (`rimba mcp`) for AI-tool integration. Install: `go install github.com/lugassawan/rimba@latest` or download from the releases page. | Optional. Falls back to `superpowers:using-git-worktrees` / `git worktree` when absent. |
| `claude-plugins-official` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | Official Anthropic plugin collection — install if you need any of its bundled tools. | Optional. |

Install them via `/plugin marketplace add …` + `/plugin install …` before using the `swe-workbench:workflow-development` skill.

## Browser automation (optional, feature-gated)

The following MCP servers enable browser-driven E2E testing and console/network diagnostics. All three are **optional** and **hard-gated**: if the required server is absent when a browser feature is invoked, the command returns a `BLOCKED:` message with a per-backend install hint rather than silently degrading.

| Server | Source | Used by | Install | Required? |
|---|---|---|---|---|
| Playwright MCP | [`microsoft/playwright-mcp`](https://github.com/microsoft/playwright-mcp) | `/swe-workbench:test --mode e2e` — browser snapshot → interact → assert spec authoring via `swe-workbench:e2e-test-writer`; also an either-or backend for `/swe-workbench:test --mode e2e-live`'s ephemeral browser walkthrough | `claude mcp add playwright npx @playwright/mcp@latest` | Required **only** for `/swe-workbench:test --mode e2e` (hard-gated: absent → `BLOCKED:`). For `/swe-workbench:test --mode e2e-live`, optional — either this or Claude-in-Chrome satisfies its gate. |
| Chrome DevTools MCP | [`ChromeDevTools/chrome-devtools-mcp`](https://github.com/ChromeDevTools/chrome-devtools-mcp) | `/swe-workbench:debug` console/network/perf diagnostics for web-UI symptoms via `read_console_messages` + `read_network_requests` | `claude mcp add chrome-devtools-mcp npx chrome-devtools-mcp@latest` | Optional; one Chrome backend required for `/swe-workbench:debug` browser diagnostics (hard-gated) |
| Claude-in-Chrome | In-harness (`mcp__claude-in-chrome__*`) | `/swe-workbench:debug` console/network capture when the Claude browser extension is connected — alternative to chrome-devtools-mcp; also an either-or backend for `/swe-workbench:test --mode e2e-live`'s ephemeral browser walkthrough (adds GIF recording via `gif_creator`) | None (provided by the Claude Code harness) | Optional alternative to chrome-devtools-mcp for `/swe-workbench:debug` browser diagnostics. For `/swe-workbench:test --mode e2e-live`, optional — either this or Playwright MCP satisfies its gate. |

**Gate behaviour:** when a browser feature is invoked and the required server is absent, the command returns `BLOCKED: … run \`claude mcp add …\` …` and stops. It does not fall back silently or produce partial results. Non-browser `/swe-workbench:test` (unit) and non-web-UI `/swe-workbench:debug` are completely unaffected by these servers.

## Language servers (optional, graceful-fallback)

<!-- verified: Claude Code 2.1.237, macOS native, 2026-08-21 -->

The harness-native `LSP` tool is main-loop-only on Claude Code 2.1.237 —
absent from every subagent's tool registry, even at the maximum grant a
subagent can hold. `bin/swe-workbench-lsp` (this plugin's own consumer, not
the 4 agents directly) closes that gap: it's a stdlib-only script that
speaks LSP JSON-RPC to a locally installed language server directly,
reachable via `Bash` from any harness.

| Server | Used by | Install | Required? |
|---|---|---|---|
| `pyright-langserver`, `gopls`, `typescript-language-server`, `rust-analyzer`, `clangd`, `jdtls`, `kotlin-language-server`, `ruby-lsp`, `sourcekit-lsp`, `csharp-ls`, `dart`, `bash-language-server` — one per `language-*` skill | `bin/swe-workbench-lsp`, invoked by `swe-workbench:reviewer`, `swe-workbench:auditor`, `swe-workbench:debugger`, `swe-workbench:refactorer` | Whatever your project stack needs, e.g. `npm i -g pyright`, `go install golang.org/x/tools/gopls@latest`; this plugin declares and installs none | Optional |

**Fallback behaviour:** unlike the browser servers above, language-server absence never blocks. Agents attempt one call via `bin/swe-workbench-lsp`. On exit 2 (a malformed anchor — the caller's own mistake), fix the anchor and retry once. On exit 3/4/5 (no server for the extension or binary missing, timeout, or server/protocol error) — or a persistent exit 2 — state `LSP unavailable — falling back to Grep` once and use `Grep` for the remainder of the run. No `BLOCKED:` sentinel, no partial results, no repeated retries beyond that one anchor-fix attempt. Run `bin/swe-workbench-lsp check` to see per-language availability without spawning a server.

## Claude Code native tools

The following tools are built into Claude Code itself — no plugin install required:

| Tool | Used for | Notes |
|---|---|---|
| `EnterWorktree(name=…)` | Creates a new worktree (if the name doesn't already exist) and enters it — moves the session CWD without restart. Use `superpowers:using-git-worktrees` as the safe wrapper: it handles consent, `.gitignore` checks, and baseline tests before calling this. | Built into Claude Code; no install needed. Verify with `claude --version`. |
| `EnterWorktree(path=…)` | Enters an existing worktree by absolute path (path must appear in `git worktree list`). Used directly by `swe-workbench:workflow-worktree-session` for mid-session switches. | same |
| `ExitWorktree(action: "keep"\|"remove")` | Returns the session to the main worktree. `"remove"` deletes the linked worktree dir; `"keep"` leaves it on disk. | same |

These are the tools `swe-workbench:workflow-worktree-session` routes to. If a tool is not found, your Claude Code version may predate its introduction — run `claude --version` and update if needed.
