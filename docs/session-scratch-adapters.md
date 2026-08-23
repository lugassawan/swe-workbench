# Session Scratch Cleanup

Session scratch cleanup clears the current harness session's scratchpad — temp files an
agent improvised during review or implementation work (a diff, a PR-body draft) and never
committed. It runs as the session-scoped block of `swe-workbench:workflow-cleanup-merged`'s
residual sweep, via `swe-workbench-reap-session-scratch`.

Cleanup is split into a **platform-neutral core** and small **platform adapters**:

- The core (`bin/swe-workbench-reap-session-scratch`) owns adapter discovery, descriptor
  parsing, every destructive-operation guard, and the sweep itself. It contains no platform
  names, native environment variables, native session-ID formats, or native filesystem
  layouts.
- Each adapter (`bin/swe-workbench-session-scratch-adapter-<platform>`) owns exactly one
  platform's knowledge: which environment variable marks an active session, what that
  platform's session IDs look like, and where its sanctioned scratch directory lives.

The split is deliberate. Scratch layouts are version-fragile harness internals — the
platform-specific half changes when a harness changes, while the deletion policy must not.
An adapter chooses what may be *considered*; the core alone decides whether anything is
safe enough to *remove*. Every unprovable case — unknown platform, ambiguous environment,
malformed descriptor, unsafe path — degrades to a zero-count no-op that still exits 0, so a
drifted harness layout can never abort a cleanup flow whose other steps already ran.

## The cleanup core

`bin/swe-workbench-reap-session-scratch` takes no path argument. It:

1. Locates its own `bin/` directory.
2. Discovers packaged executable siblings named `swe-workbench-session-scratch-adapter-*`.
3. Invokes every adapter under a versioned protocol, treating adapter output as untrusted data.
4. Requires exactly one active, valid adapter and exactly one candidate target.
5. Validates the adapter's authorized root and relative candidate with platform-neutral
   invariants (see [Safety policy](#safety-policy)).
6. Clears the target's *contents* while preserving the target directory — a later merge
   round in the same session may still write to it.
7. Emits exactly one `SWEPT_SESSION_FILES=<n>` assignment (a top-level entry count, not a
   recursive file count) and exits zero.

`swe-workbench-reap-session-scratch` is invoked by
`skills/workflow-cleanup-merged/scripts/sweep-residuals.sh`; neither that script nor
`skills/workflow-cleanup-merged/SKILL.md` detects platforms or calls adapters directly.
Adding a platform never touches the cleanup workflow.

## Adapter discovery

The core discovers only sibling files matching:

```text
swe-workbench-session-scratch-adapter-*
```

Discovery is sibling-relative by design: `package.json` already ships `bin/swe-workbench-*`,
runtime scripts already resolve siblings from their own location, and no user-controlled
search path or adapter directory is ever consulted. The reaper resolves adapters from its
own directory — not `PATH`, not the current working directory, not an environment override,
not `$CLAUDE_PLUGIN_ROOT`.

| Discovery outcome | Core behavior |
|---|---|
| No adapters packaged | Safe no-op |
| No adapter active | Safe no-op |
| Exactly one active, valid adapter | Validate its candidate |
| More than one active adapter | Ambiguous environment — safe no-op |
| Active adapter emits malformed/unsafe output | Safe no-op |

There is no platform precedence. A nested environment that exposes multiple harness session
markers (a Claude session dispatching a Pi subagent, say) is ambiguous, not a license to
pick a winner.

## Adapter protocol

### Invocation and exit statuses

The core executes each adapter with no arguments. Adapters are trusted packaged code, but
their output is parsed as untrusted data — a bug in an adapter's path construction must
fail closed, not widen the deletion boundary.

| Status | Meaning | Core behavior |
|---|---|---|
| `0` | Active adapter; descriptor emitted | Parse and consider the descriptor |
| `3` | Adapter is inactive (not this platform) | Ignore the adapter |
| Any other | Active platform, but no provably safe target | Diagnostic + zero-count no-op for the entire sweep |

Status `3` versus other non-zero is the load-bearing distinction: "not this platform" is
routine, while "this platform, but cleanup cannot be proven safe" is always surfaced.

### Descriptor format

A successful adapter emits UTF-8 text, one record per line:

```text
SWB_SESSION_SCRATCH_V1
<adapter-id>
<absolute-authorized-root>
<candidate-count>
<relative-candidate-1>
...
```

- The protocol marker must match exactly; the marker is versioned so a future incompatible
  format never silently reinterprets old output.
- Adapter IDs match `^[a-z0-9][a-z0-9-]*$` and are diagnostic only.
- The authorized root is absolute.
- The candidate count is a non-negative decimal integer equal to the number of records
  that follow; exactly one candidate survives validation.
- Candidate paths are relative, with no empty, `.` or `..` components.
- Adapters reject dynamic values containing carriage return or newline before emission;
  newline-containing POSIX paths are unsupported by design and produce a safe no-op. The
  limitation keeps the protocol auditable in plain Bash.
- The core parses records as data — never `eval`, never `source`. Extra or missing records
  invalidate the whole descriptor.

## Safety policy

After one descriptor and one candidate survive the protocol checks, the core applies all
of the following. Any failure is a zero-count no-op that leaves the target untouched.

**Authorized root**

- Absolute, not `/`, an existing directory, not a symlink, owned by the current effective
  user, and canonicalizable.

**Relative candidate**

- At least two path components — the authorized root or its immediate child can never
  become the sweep target.
- No leading `/`; no empty, `.`, or `..` components.
- Every existing component from the root through the target is a real directory, not a
  symlink — an escape planted at *any* depth is rejected.

**Canonical target**

- Canonicalizes to a strict descendant of the canonical authorized root (re-checked
  immediately before removal begins — the check-to-delete window is minimized, though
  portable Bash cannot close it entirely).
- Exists, is a directory, is not a symlink, is owned by the current user.
- Contains no top-level `.git` entry — keeping scratch and worktree domains disjoint by
  construction.

**Removal**

- `nullglob` and `dotglob` are enabled only around enumeration and removal, so hidden
  entries are swept and counted like any other.
- Each top-level entry is removed with `rm -rf --`; `SWEPT_SESSION_FILES` increments only
  on success. A failed removal warns on stderr and leaves the entry in place.
- The target directory itself is never removed.

## Packaged adapters

### Claude Code

`bin/swe-workbench-session-scratch-adapter-claude` preserves the historical contract:

- Active marker: non-empty `CLAUDE_CODE_SESSION_ID`.
- Session-ID grammar: 36-character hex-and-hyphen UUID shape.
- Authorized root: `/tmp/claude-<uid>` (tolerant of the platform's canonical `/tmp`
  spelling).
- Candidate shape: `<project>/<session-id>/scratchpad`, matched by glob; exactly one match
  is required, reported relative to the root.

### Pi Coding Agent

`bin/swe-workbench-session-scratch-adapter-pi` detects Pi and deliberately resolves
nothing:

- Active marker: non-empty `PI_SESSION_ID`; the marker is rejected if it contains control
  characters.
- Pi (through 0.84.2) documents session metadata (`PI_SESSION_ID`, optional
  `PI_SESSION_FILE`, configurable session storage) and JSONL session files — but no
  sanctioned session scratch directory. The adapter therefore returns its
  active-but-unsupported status and cleanup reports `SWEPT_SESSION_FILES=0`.
- It never infers a target from `PI_SESSION_FILE`, `PI_CODING_AGENT_SESSION_DIR`,
  `--session-dir`, or the JSONL session location, and never borrows Claude's
  `/tmp/claude-<uid>` namespace. Retention is the only safe behavior without a sanctioned
  path contract.

When Pi grows a sanctioned scratch contract — or swe-workbench adopts its own
scratch-writing lifecycle — only the Pi adapter, its tests, and this page change. The
core and the cleanup workflow stay untouched; that is the point of the boundary.

## Failure behavior

Diagnostics go to stderr; the machine-readable count goes to stdout; exit is always 0.

| Condition | Result |
|---|---|
| No active platform | Zero-count no-op |
| Multiple active platforms | Zero-count no-op with ambiguity diagnostic |
| Invalid native session ID | Zero-count no-op |
| Platform has no sanctioned scratch contract | Zero-count no-op |
| Malformed adapter descriptor | Zero-count no-op |
| Zero or multiple candidates | Zero-count no-op |
| Unsafe root or target | Zero-count no-op |
| Target disappears before removal | Zero-count no-op |
| One entry fails removal | Continue with the rest; count only successes |

No adapter failure can abort `swe-workbench:workflow-cleanup-merged` or suppress the
count assignment.

## Testing

- `tests/test_reap_session_scratch.py` — core contract. Runs a copy of the reaper from an
  isolated temp `bin/` containing only explicit fake adapters, with neutral names and
  paths. Covers discovery/ambiguity, protocol and descriptor validation, every safety
  guard (symlinks at each depth, root escape, ownership, `.git`, disappearance), hidden
  entries, top-level counting, directory preservation, idempotence, partial-removal
  counting, signal interruption, and the exactly-one-assignment/exit-zero contract.
  Subprocesses are invoked with argument lists and explicit environments — never
  `shell=True`.
- `tests/test_session_scratch_adapters.py` — adapter contracts. Per platform: active and
  inactive detection, native ID grammar, native root and candidate shape, zero and
  ambiguous candidates, line-breaking value rejection, descriptor compliance, and (for
  Pi) proof that `PI_SESSION_FILE` cannot authorize a target.
- `tests/conftest.py` — `_CLEAN_ENV` strips *both* `CLAUDE_CODE_SESSION_ID` and
  `PI_SESSION_ID`, so a suite run inside a live session can never resolve and wipe that
  session's real scratchpad. Tests opt in with fake marker values.
- `tests/test_bin_scripts.py` — closed-world bin inventory: both adapters are tracked as
  Bash executables with the mandatory shebang and syntax checks.

Verification commands:

```bash
python3 -m pytest tests/test_reap_session_scratch.py tests/test_session_scratch_adapters.py -q
python3 -m pytest -q
bash -n bin/swe-workbench-reap-session-scratch bin/swe-workbench-session-scratch-adapter-*
```

## Adding an adapter

Adding a platform is adapter work only — the core, the workflow, and every existing test
stay untouched:

1. Create `bin/swe-workbench-session-scratch-adapter-<id>` — executable, Bash, with a
   short native-contract header stating the authorized layout (or, for an unsupported
   platform, that no target is authorized and why).
2. Implement the protocol: `exit 3` when inactive, `exit 4` (or any non-zero ≠ 3) when
   active-but-unresolvable, otherwise emit the `SWB_SESSION_SCRATCH_V1` descriptor.
3. Add the platform's native session marker to the `_CLEAN_ENV` denylist in
   `tests/conftest.py` — this is the live-session safety net, not optional hygiene.
4. Add the command to `tests/test_bin_scripts.py`'s `SCRIPTS` inventory.
5. Add adapter-contract tests alongside the existing ones, including a fixture that
   proves the marker's absence/presence drives the right exit status.
6. Document the platform in this page's [Packaged adapters](#packaged-adapters) section.

Removing an adapter disables that platform and nothing else. Keep adapters small; there
is deliberately no registry, plugin loader, or configuration language — executable
sibling discovery is the whole mechanism, and a third functional adapter is the bar at
which introducing one should even be reconsidered.

## Operational notes

- **Pi reports zero swept files** until a sanctioned Pi scratch path exists — that is the
  adapter working as designed, not a malfunction. Watch Pi release notes and extension
  APIs for an explicit scratch location.
- **Ambiguity diagnostics** in nested-agent environments mean multiple harness markers
  were ambient; the reaper no-ops there on purpose.
- **Zero-candidate diagnostics after a harness upgrade** usually mean path drift: check
  the adapter's native layout against the new harness version.
- **Adapter roots are security-sensitive constants.** An overly broad root is the one
  mistake the core's downstream guards cannot fully undo; review them first in any
  adapter change.
- **Intermittent partial-removal failures** warrant investigation (TOCTOU replacement is
  the classic cause) — never a weakening of the guards to make the symptom disappear.
