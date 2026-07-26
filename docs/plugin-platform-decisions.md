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
