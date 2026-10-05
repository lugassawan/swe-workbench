# Plugin platform decisions — hooks.json wiring

Rulings on `hooks/hooks.json` wiring and what its entries may carry. Recorded here so
they don't have to be re-litigated. Sibling rulings live in the other topic docs (indexed in
`docs/README.md`).

## 1. Hook `if` conditions — considered, not adopted

`.claude-plugin/schemas/plugin.schema.json` defines the command-hook object as `{type, command,
if, shell, timeout, statusMessage, once, async, asyncRewake}`. `if` is documented as *"Permission
rule syntax to filter when this hook runs (e.g. `Bash(git *)`). Only runs if the tool call matches
the pattern."* — it filters a tool-call payload against a pattern; it is not a general-purpose
guard.

Applied to every entry in `hooks/hooks.json`, no `if` buys anything:

| Hook | Event | Why `if` buys nothing |
|---|---|---|
| `bash_guard.sh` | `PreToolUse` / `Bash` | `Bash(*)` is exactly redundant with `matcher` |
| `skill_usage_record.sh` | `PreToolUse` / `Skill` | `Skill(*)` is exactly redundant with `matcher` |
| `worktree_permission_grant.sh` | `PreToolUse` / `Read\|Edit\|Write` | Worktree root is runtime-resolved, not a static path rule |
| `secret_guard.py` | `PreToolUse` / `Write\|Edit` | Same as `worktree_permission_grant.sh` — no static pattern captures "contains a credential" |
| `handoff_guard.py` | `PreToolUse` / `Bash\|Edit\|Write` | Lease ownership is runtime-resolved per worktree, not a static path/pattern rule |
| `skill_autoload_hint.sh` | `PostToolUse` / `Read\|Edit\|Write` | Would need every extension enumerated; a miss silently loses the hint |
| `skill_usage_flush.sh` | `SubagentStop` | No tool call to match against — inert at best, disabling at worst |
| `workflow_resume_hint.sh` ×3 | `SessionStart` | Same — lifecycle events carry no tool call |
| `memory_hint.sh` ×3 | `SessionStart` | Same — lifecycle events carry no tool call |

**Ruling: no `hooks.json` entry may carry an `if` key**, enforced by
`scripts/validate.py:check_hooks_json()`. This is strictly stronger than the two security
controls (`bash_guard.sh`, `secret_guard.py`) that originally motivated the question — every entry
in the table above hits the same failure mode: `if` is one more predicate that can silently
disable a hook (a miss reads as "hook chose not to fire," not as an error) for zero filtering
benefit over what `matcher` already provides or what the script can check for itself at runtime.

## 2. Guard verdict contract and CWD attribution

`bash_guard.sh` emits a three-valued verdict over a two-valued exit-code wire, and attributes its
repo-sensitive checks (implicit-refspec force push, `git reset --hard`) to the directory the
command actually targets rather than the hook process CWD.

**Wire contract** (exit codes stay `{0, 2}` — any other code still means "guard did not run"
and follows each guard's fail posture):

| Verdict | Wire shape |
|---|---|
| `allow` | exit 0, empty stdout — silent |
| `warn` | exit 0, exactly one line of stdout JSON: `hookSpecificOutput.permissionDecision` `"allow"` + `permissionDecisionReason` (the semantic channel), mirrored in a top-level `systemMessage` (Claude Code's user-visible warning surface) |
| `block` | exit 2, stderr only — never emits stdout JSON, byte-compatible with the pre-warn contract |

Verdict precedence is `block > warn > allow`: a warn accumulated anywhere in the command is
suppressed when any segment blocks. The reason string is decided once, at the guard — adapters
translate presentation only (Claude Code consumes the JSON natively; `pi/extensions/guards.ts`
reads `permissionDecisionReason` and surfaces it via `ctx.ui.notify` when a dialog-capable UI
exists — TUI and RPC — or a display-only `sendMessage` custom message in non-interactive mode).
Malformed stdout is a silent allow: a warn must never block or throw on its own output shape.
Watch-signal: Claude Code displaying both `systemMessage` and the allow-reason would double-show
one warning — harmless, but worth noting if it surfaces.

**Attribution semantics.** Base dir = the payload's top-level `cwd` when absolute (Claude Code
provides it; the Pi adapter passes `ctx.cwd`), else the guard process CWD. A conservative
in-script resolver folds the command's segments: a `cd` folds into the state only for commands
later in the same `&&`-chain (their execution is gated on the cd succeeding); at an
unconditional separator a chain that touched a cd commits the state to *uncertain*, because
follow-ups run whether or not the cd succeeded. `git -C <dir>` overrides per segment. A cd in a
pipeline stage, background chain, subshell, or substitution cannot affect the parent shell and
neither folds nor taints; wrapper segments (`bash -c`, `ssh`, `docker exec`, …) re-parse their
arguments in another shell and attribute uncertain.

**Behavior matrix** (target = resolved dir, base = session cwd):

| Resolution | Target branch | Verdict |
|---|---|---|
| confident, target ≠ base | protected | block (message cites the target) |
| confident, target ≠ base | non-protected | allow + warn (re-attribution message) |
| confident, target == base | protected / non-protected | block / silent allow — pre-attribution behavior unchanged |
| uncertain | protected (per base) | block — legacy check verbatim |
| uncertain | non-protected | allow + warn (attribution-uncertain message) |

**Never-shrinks guarantee:** uncertain attribution runs the legacy process-CWD check byte-identically
and may only *add* the allow-side warn — the block set cannot shrink. Attribution identity is
resolved by `git -C <dir> rev-parse` itself (symlinks included), never by path-prefix matching.
Resolvable path forms: absolute literals, `~`/`$HOME`, relative literals without `..` components;
everything else — variables, command substitution, `..` components, `cd -`, `pushd` — is
uncertain. A resolvable subdir of the base repo counts as target ≠ base (the warn fires); same-repo
noise suppression is deliberately not implemented. Two resolver invariants pinned by fixtures:
a command right of `||` runs only when the left side failed, so a cd left of `||` never keeps its
folded target for the chain tail; and only the literal token `cd` folds — a pathed `cd` is an
external binary that cannot change the parent cwd. Repo-redirecting git flags (`--git-dir`,
`--work-tree`, `--namespace`) decide the repo elsewhere and attribute uncertain. One deliberate
detection-scope change vs the pre-tokenization reset scan: a quoted `git reset --hard` mention
inside another git command (e.g. a commit message) no longer matches — the tokenized scan does
not resume after a non-reset subcommand, so that pre-existing over-block is gone.

**Considered, not adopted:** a third exit code for warn — `guards.ts` treats any code outside
`{0, 2}` as guard failure (fail-closed for `bash_guard.sh`), so it would demand a lockstep
two-harness change and rewrite the documented two-code contract for zero benefit over stdout
JSON. Adapter-side cd resolution — attribution is a verdict *input*, and duplicating it per
harness in two languages is exactly where verdict drift would live. Probe execution (`cd X &&
git rev-parse` in a subshell for ground truth) — executing fragments of untrusted input breaks
the guard's purity.

**Out of scope here:** cross-segment force-flag classification (a `-f` in one segment must not
be laundered by another segment's argv) — an independent fix with its own failure modes.
