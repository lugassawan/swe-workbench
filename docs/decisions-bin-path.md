# Plugin platform decisions — bin/, PATH, and plugin-local state

Rulings on `bin/` wrappers, PATH resolution, and plugin-local state, made while migrating
skills, commands, and agents to invoke plugin scripts as bare PATH commands instead of
resolving them through `$CLAUDE_PLUGIN_ROOT`, while collapsing the resulting
`runtime/`/`bin/` wrapper split back into a single `bin/` directory and retiring the
`CLAUDE_PLUGIN_ROOT` injector hook. Recorded here so they don't have to be re-litigated.
Sibling rulings live in the other `docs/decisions-*.md` files (indexed in
`docs/README.md`).

## 1. `${CLAUDE_PLUGIN_DATA}` — considered, not adopted

Some plugin runtimes expose a `CLAUDE_PLUGIN_DATA` directory for a plugin's own persistent
state. swe-workbench's workflow-state feature doesn't use it.

State lives at `<git-toplevel>/.claude/cache/workflow-state/<branch>.json` (see
`shared/docs/workflow-state.md`) — per-repo and per-branch by construction, because the path is
derived from `git rev-parse --show-toplevel` and the current branch name. `CLAUDE_PLUGIN_DATA`
is global-per-plugin: adopting it would require hashing the repo path (and branch) into the
filename to avoid collisions across repos and branches — added complexity for no win over the
git-toplevel-relative path already in use.

## 2. Dev-loop caveat: `bin/` changes cannot be dogfooded in-repo

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

## 3. `swe-workbench-skill-script` dispatcher replaces the doctor-anchor `_RT=` derivation

**(a) Why the doctor-anchor derivation was replaced.** Once `runtime/` collapsed into `bin/` and
the `CLAUDE_PLUGIN_ROOT` injector hook was retired, skills with their own `scripts/` helpers
(`swe-workbench:workflow-cleanup-merged`, `swe-workbench:workflow-branch-sync`) still needed to resolve a skill-local path, so
a stand-in root derivation —
`_RT="$(cd "$(dirname "$(command -v swe-workbench-doctor)")/.." && pwd)"` — was introduced at every
call site. That traded one copy-pasted preamble for another: 10 occurrences across 2 files, and
still path construction living in skill prose rather than in a script — the same shape of
duplication `bin/README.md`'s "Reference pattern" exists to prevent for every other `bin/` script.
`bin/swe-workbench-skill-script <skill> <script> [args...]` owns that resolution once, as a
dispatcher: skill prose invokes it as a bare command, with no `_RT`/`_SCRIPTS` variables anywhere.

**(b) Why the `command -v swe-workbench-<name>` guard itself is not extractable.** A PATH-
availability guard cannot live inside a PATH-resolved helper. If `bin/` is off `PATH`, the helper
(dispatcher or otherwise) is unreachable too — the caller gets the shell's bare
`command not found` (exit 127) instead of the guard's actionable message ("reinstall or update the
swe-workbench plugin"). The guard has to run *before* anything that depends on `bin/` being on
`PATH`, which rules out delegating it to a script that is itself only reachable via `PATH`. It
stays exactly where it is today: one `command -v` line at the top of each skill's first executable
block, per `bin/README.md`'s "Reference pattern".
