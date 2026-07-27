# Plugin platform decisions

Rulings made while migrating `runtime/` callsites to `bin/` wrappers, so skills, commands, and
agents invoke plugin scripts as bare PATH commands instead of resolving them through
`$CLAUDE_PLUGIN_ROOT`. Recorded here so they don't have to be re-litigated once `runtime/` and
the `CLAUDE_PLUGIN_ROOT` injector hook are eventually retired.

## 1. `${CLAUDE_PLUGIN_DATA}` — considered, not adopted

Some plugin runtimes expose a `CLAUDE_PLUGIN_DATA` directory for a plugin's own persistent
state. swe-workbench's workflow-state feature doesn't use it.

State lives at `<git-toplevel>/.claude/cache/workflow-state/<branch>.json` (see
`docs/workflow-state.md`) — per-repo and per-branch by construction, because the path is
derived from `git rev-parse --show-toplevel` and the current branch name. `CLAUDE_PLUGIN_DATA`
is global-per-plugin: adopting it would require hashing the repo path (and branch) into the
filename to avoid collisions across repos and branches — added complexity for no win over the
git-toplevel-relative path already in use.

## 2. No `claude plugin validate` in CI, and no frontmatter allowlist validator

CI's `scripts/validate.py` gate is deliberately **open-world**: `check_agents()` and friends
assert *positive, closed-form* invariants this repo owns and controls (frontmatter fields
present, references resolve, line caps respected) rather than validating against an external
schema.

Two things were considered and rejected for the same reason:

- **Running `claude plugin validate` (or equivalent) in CI** — this validates against a schema
  the CLI ships, not one this repo version-controls. An upstream schema change would turn any
  unrelated PR into a red build, with no maintainer able to fix it locally (the fix lives in a
  different repository entirely).
- **A frontmatter-key allowlist validator** — same failure mode: a new frontmatter key the
  platform adds would fail closed-world validation here until this repo's allowlist catches up,
  even though the key is valid and harmless.

Prefer assertions the repo can always satisfy by editing its own files.

## 3. Dev-loop caveat: `bin/` changes cannot be dogfooded in-repo

`<plugin>/bin` is appended to the Bash tool's `PATH` for the **installed plugin cache**
(`…/cache/swe-workbench/swe-workbench/<version>/bin`), not for a local dev checkout. This has
two consequences:

- A bare `swe-workbench-*` command typed inside this repo's own working tree resolves to the
  **released** wrapper, not the one just edited in the checkout. Testing a `bin/` change
  requires invoking the wrapper by path (`bash bin/swe-workbench-doctor`) or reinstalling the
  plugin from the branch under test — bare-command invocation alone will not pick up local
  edits.
- Plugin `bin/` directories are appended to the **end** of `PATH` (after `/usr/bin`, Homebrew,
  etc.), not prepended. A wrapper without the `swe-workbench-` prefix would therefore be
  *shadowed by* a same-named binary already on the user's PATH, not the other way around. The
  prefix requirement stands regardless of this ordering — PATH placement is not something this
  repo controls or should rely on — but it's worth recording that the shadowing direction is the
  opposite of what might be assumed.

## 4. Hook `if` conditions — considered, not adopted

`.claude-plugin/schemas/plugin.schema.json` defines the command-hook object as `{type, command,
if, shell, timeout, statusMessage, once, async, asyncRewake}`. `if` is documented as *"Permission
rule syntax to filter when this hook runs (e.g. `Bash(git *)`). Only runs if the tool call matches
the pattern."* — it filters a tool-call payload against a pattern; it is not a general-purpose
guard.

Applied to every entry in `hooks/hooks.json` (issue #557), no `if` buys anything:

| Hook | Event | Why `if` buys nothing |
|---|---|---|
| `bash_guard.sh` | `PreToolUse` / `Bash` | `Bash(*)` is exactly redundant with `matcher` |
| `inject_plugin_root.sh` | `PreToolUse` / `Bash` | Same |
| `skill_usage_record.sh` | `PreToolUse` / `Skill` | `Skill(*)` is exactly redundant with `matcher` |
| `worktree_permission_grant.sh` | `PreToolUse` / `Read\|Edit\|Write` | Worktree root is runtime-resolved, not a static path rule |
| `secret_guard.py` | `PreToolUse` / `Write\|Edit` | Same as `worktree_permission_grant.sh` — no static pattern captures "contains a credential" |
| `skill_autoload_hint.sh` | `PostToolUse` / `Read\|Edit\|Write` | Would need every extension enumerated; a miss silently loses the hint |
| `skill_usage_flush.sh` | `SubagentStop` | No tool call to match against — inert at best, disabling at worst |
| `workflow_resume_hint.sh` ×3 | `SessionStart` | Same — lifecycle events carry no tool call |

**Ruling: no `hooks.json` entry may carry an `if` key**, enforced by
`scripts/validate.py:check_hooks_json()`. This is strictly stronger than the two security
controls (`bash_guard.sh`, `secret_guard.py`) that originally motivated the question — every entry
in the table above hits the same failure mode: `if` is one more predicate that can silently
disable a hook (a miss reads as "hook chose not to fire," not as an error) for zero filtering
benefit over what `matcher` already provides or what the script can check for itself at runtime.

Cross-reference: #547, #557.
