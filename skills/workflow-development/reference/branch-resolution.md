# Phase 1 — Branch Resolution

**Goal:** Isolated workspace with clean baseline.

**Worktree provider detection:**

```sh
# Prefer rimba MCP server when active in the session (no shell needed).
# Otherwise resolve the binary: PATH first, then common install locations.
# NOTE: use `rimba version` (subcommand) to print the version; `rimba --version`
#       is not a recognised flag and exits non-zero.
RIMBA=$(command -v rimba 2>/dev/null \
  || { [ -x "$HOME/.local/bin/rimba" ] && echo "$HOME/.local/bin/rimba"; } \
  || { [ -x "$HOME/go/bin/rimba" ]     && echo "$HOME/go/bin/rimba"; } \
  || true)
[ -n "$RIMBA" ] && "$RIMBA" version 2>/dev/null || true   # confirm binary; never `--version`
```

- **Detect an existing worktree first (idempotent resume; rimba absent → see that bullet below):** rimba MCP active → call `list`; rimba CLI → run `$RIMBA list --json` (entries carry `task`, `type`, `branch`, `path`, `is_current`, `status.dirty`). Match an entry whose `task` equals the target task (PR invocations: target key is `pr:<num>`) **or** whose `branch` equals the derived `<prefix>/<task>`. **On a match:** resolve the absolute path via `git worktree list --porcelain`, keyed on the matched entry's own `branch` value — not a re-derived `<prefix>/<task>` guess, which can miss after a `rimba rename` or a task-only match. Print exactly one notice line: `Resuming existing worktree: <branch> at <abs-path>` (append ` (uncommitted changes present)` if the entry's `status.dirty` is true — already fetched above, no extra call needed). If deps/install status is unknown (the worktree's own `rimba add` ran in a prior, possibly-dead session, so there is no process to wait on), confirm by checking the stack's install marker (`node_modules`, `.venv`, vendored deps) — no dedicated install-command detection marker exists in this skill, so lean on the marker check rather than guessing a command; don't run tests until confirmed. Follow "Enter the worktree" below, then **skip the create call entirely** — this pre-check runs *before* any `add` is launched, so a match is always a *prior* worktree. **No match → create**, using the bullets below.
- **rimba MCP server active:** invoke the `add` tool on it (`rimba mcp`) — no shell process needed. Use `add pr:<num>` when implementing from a PR number. Same non-zero-exit error-routing applies as the `$RIMBA` binary path below (an error reporting the worktree/branch already exists routes to enter; any other error is reported verbatim with a retry/fallback prompt) — the in-flight streaming behavior itself is CLI-specific and doesn't apply to an MCP tool call.
- **`$RIMBA` non-empty (binary found):** run `$RIMBA add [<service>/]<task> [--flag]` (or `$RIMBA add pr:<num> --task "<label>"` for a PR). Rimba handles branch-prefix conventions (`feature/`, `bugfix/`, `hotfix/`, `docs/`, `test/`, `chore/`), `.env`/`.tool-versions`/`.vscode` copying, `post_create` hooks, and lockfile sharing. **In-flight ≠ duplicate:** `Path: <abs-path>` prints *before* `post_create` hooks/deps finish (see "Post-create timing" and "Reclaim install time" below) — a path appearing while *this* `rimba add` is still running is the normal early print, **never** a duplicate; never kill or interrupt it. Only a genuine **non-zero exit** reporting the worktree/branch already exists — a real duplicate from another session — routes to enter: resolve the path via `git worktree list --porcelain`, print the same notice as above (dirty flag via `git -C <path> status --porcelain`, since no `list` call ran in this path), and `EnterWorktree` it instead of surfacing a failure. For any other non-zero exit, report the error verbatim and ask the user whether to retry or fall back to `superpowers:using-git-worktrees` — do not silently swallow it.
- **Promote work already started** — if you began editing on the current branch in the main checkout (not the default branch), `$RIMBA add branch:<current-branch>` moves that work into its own worktree, transferring dirty changes via `git stash`. `--source` is not valid in this mode. Distinct from the resume case above: that re-enters a worktree left over from a *prior* run; this promotes uncommitted work on the *current* branch in the main checkout into a new worktree.
- **rimba absent:** before invoking `superpowers:using-git-worktrees`, run `git worktree list --porcelain` and match the target branch the same way as the pre-check above; if a match exists, `EnterWorktree` it (same one-line notice + dirty flag via `git -C <path> status --porcelain`) instead of creating. Otherwise invoke `superpowers:using-git-worktrees` exactly as today.

**Picking the branch-prefix flag** — derive from the commit-tag the change will carry (see `swe-workbench:workflow-commit-and-pr` for the full taxonomy):

| Work type | rimba flag | Branch prefix | Commit-tag |
|---|---|---|---|
| New feature *(default)* | *(none)* | `feature/<task>` | `[feat]` |
| Bug fix | `--bugfix` (alias `--fix`) | `bugfix/<task>` | `[fix]` |
| Hotfix | `--hotfix` | `hotfix/<task>` | `[hotfix]` |
| Documentation | `--docs` | `docs/<task>` | `[docs]` |
| Tests | `--test` | `test/<task>` | `[test]` |
| Chore / tooling | `--chore` | `chore/<task>` | `[chore]` |

Examples: `$RIMBA add auth-redirect --bugfix` → `bugfix/auth-redirect`; `$RIMBA add ci-matrix --chore` → `chore/ci-matrix`.

**Monorepo scope** — in a monorepo, prefix the task with the service or package name using `<service>/<task>`. The type flag still controls the branch prefix:

- `$RIMBA add backend-api/auth-redirect --bugfix` → `bugfix/backend-api/auth-redirect`
- `$RIMBA add frontend/dark-mode` → `feature/frontend/dark-mode`

Use the service scope whenever the work is clearly contained within one module — it groups branches and makes worktree paths self-descriptive. For cross-cutting changes, inspect the planned file edits and pick the service where the majority of changes land. If two services tie, prefer the service that owns the primary interface changed (e.g. the API layer for a contract change, the UI layer for a rendering change); only omit the scope entirely if no service file is touched at all (e.g. a root-only CI config change).

**Post-create timing** — `rimba add` runs dependency install and `post_create` hooks *after* creating the worktree. `Path: <abs-path>` is printed **before deps** install begins (after the create + copy steps). Coding may start as soon as `Path:` appears; running the test suite requires installed packages, so wait for `rimba add` to fully complete before running tests. This is the same early print the "In-flight ≠ duplicate" rule above guards against misreading as a duplicate worktree.

- **Deps required (most stacks):** omit `--skip-deps`/`--skip-hooks` and wait for `rimba add` to complete before running the test suite. This applies regardless of whether the plan is TDD-first — if tests need installed packages, rimba must finish first.
- **No deps needed:** pass `--skip-deps` and `--skip-hooks` only when the test suite requires no installation step (e.g. pure shell scripts, documentation assertion tests). Never skip deps and then reinstall them manually — rimba's pipeline already handles it correctly.

**Reclaim install time (large/monorepo deps)** — `Path:` is available before deps finish, so on a long install you can implement during the wait. A path becoming visible mid-run is never grounds to kill the in-flight `rimba add` (see "In-flight ≠ duplicate" above):
1. Run `rimba add`; if install will take a while, let it continue in the **background** (the Bash tool backgrounds long-running commands) so the session is free to code.
2. As soon as `Path: <abs-path>` appears, enter the worktree and implement the planned changes.
3. **Do not run the test suite until `rimba add` has fully completed** — RED/GREEN need installed deps.
4. Once rimba finishes, reconcile with TDD: `git stash` the implementation you wrote in step 2 → write the failing test → run (**RED** — fails with implementation stashed, confirming the test exercises the new behaviour) → `git stash pop` → run again (**GREEN**).

Skip this optimisation when install is fast, `--skip-deps`/`--skip-hooks` already apply (no wait), or `post_create` hooks rewrite the files you'd edit (let hooks finish first).

**Enter the worktree:** After `Path: <abs-path>` appears, try `EnterWorktree(path=<abs-path>)`. From the main session this works for any git-registered worktree (including rimba's `../<repo>-worktrees/` layout). If rejected because the session is already inside a **different worktree** (target path outside `.claude/worktrees/`), the primary remedy is `ExitWorktree(action=keep)` → return to main → retry `EnterWorktree(path=<abs-path>)` (re-anchors session caches). Fall back to `cd <abs-path>` via Bash only as a last resort for non-rimba checkouts with no `.claude/worktrees` infrastructure; `cd` only anchors the Bash persistent cwd and does not re-anchor session-level caches the way `EnterWorktree` does. On any resumed or continued session, try `EnterWorktree(path=<worktree-path>)` first; if rejected because the session is already inside a different worktree, call `ExitWorktree(action=keep)` → retry; otherwise re-`cd <worktree-path>` as a last resort for non-rimba checkouts only (Bash cwd does not persist across session resume, so `cd` must be re-issued each time — unlike `EnterWorktree`, which restores it automatically).

Verify baseline tests pass before writing any code.
