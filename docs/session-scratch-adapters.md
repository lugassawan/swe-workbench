# Platform-Agnostic Session Scratch Cleanup Design

**Issue:** [#647](https://github.com/lugassawan/swe-workbench/issues/647)  
**Status:** Approved  
**Date:** 2026-08-23

## Summary

Replace the Claude-specific session scratch reaper with a platform-neutral cleanup core and separately packaged platform adapters. The core discovers adapters, consumes a strict descriptor, enforces one shared fail-closed deletion policy, clears a verified target's contents, and preserves the target directory. Platform-specific environment variables, session-ID grammars, filesystem layouts, and candidate discovery remain outside the core.

The initial Claude adapter preserves current behavior. The initial Pi adapter detects Pi but returns no target because Pi 0.84.2 documents session metadata and JSONL storage, not a sanctioned session scratch directory. It must not infer a path from `PI_SESSION_FILE`, borrow Claude's layout, or authorize arbitrary `/tmp` paths. Functional Pi sweeping can be added by changing only the Pi adapter when a sanctioned path contract exists.

## Goals

- Keep `swe-workbench-reap-session-scratch` free of platform names, native environment variables, native ID formats, and native path layouts.
- Add a platform by shipping one adapter without changing cleanup-core logic or the cleanup workflow.
- Preserve content-only removal, top-level entry counting, idempotence, exit-zero behavior, and `SWEPT_SESSION_FILES=0` on every unresolved or unsafe case.
- Keep platform discovery and path authority explicit and reviewable.
- Prevent an adapter's malformed output from widening the deletion boundary.
- Test the generic safety policy independently from native harness behavior.

## Non-goals

- Creating a scratch directory for Pi or changing where agents write temporary files.
- Treating `PI_SESSION_FILE` or Pi's configurable JSONL session directory as scratch storage.
- Supporting runtime installation of third-party adapters outside the packaged plugin.
- Designing a general plugin framework or configuration language.
- Making recursive deletion atomic; portable Bash cannot eliminate all validation-to-removal races.
- Cleaning scratch from inactive or previous sessions.

## Architecture

### Components

#### Platform-neutral cleanup core

`bin/swe-workbench-reap-session-scratch` is the stable policy owner. It:

1. Locates its own `bin/` directory.
2. Discovers packaged executable siblings named `swe-workbench-session-scratch-adapter-*`.
3. Invokes every adapter under a controlled, versioned protocol.
4. Requires exactly one active, valid adapter and exactly one candidate.
5. Validates the adapter's authorized root and relative candidate using platform-neutral invariants.
6. Clears the target's contents while preserving the target directory.
7. Emits `SWEPT_SESSION_FILES=<n>` and exits zero.

The core must not contain `CLAUDE_*`, `PI_*`, `claude`, `pi`, native ID regexes, or native filesystem roots.

#### Platform adapters

Initial adapters are:

```text
bin/swe-workbench-session-scratch-adapter-claude
bin/swe-workbench-session-scratch-adapter-pi
```

An adapter owns:

- Detection of its native session environment.
- Validation of its native session identifier.
- Selection of an explicitly sanctioned root.
- Native path-shape checks and candidate discovery.
- Rejection of dynamic values containing line breaks.
- Platform-specific diagnostics.

An adapter never removes files. It can authorize only targets beneath the root it reports; the core independently verifies that boundary.

#### Cleanup workflow

`skills/workflow-cleanup-merged/SKILL.md` and `sweep-residuals.sh` continue to invoke only `swe-workbench-reap-session-scratch`. They do not detect platforms or call adapters directly.

### Dependency direction

The cleanup workflow depends on the platform-neutral reaper contract. The reaper depends on the adapter protocol, not on Claude or Pi behavior. Native adapters depend on their harness environments and implement the outward-facing protocol.

This is proportional Clean Architecture: the safety policy points toward a stable descriptor contract, while environment-specific details remain adapters at the boundary. Separate packages, dependency-injection frameworks, and a general registry would add ceremony without improving this Bash utility.

DDD does not apply because this is a technical utility without a complex business domain, aggregates, or bounded contexts.

## Adapter Discovery

The core discovers only sibling files whose names match:

```text
swe-workbench-session-scratch-adapter-*
```

This location is deliberate:

- `package.json` already ships `bin/swe-workbench-*`.
- Runtime scripts already resolve siblings relative to their own location.
- No user-controlled search path or adapter directory is consulted.
- Adding an adapter changes packaging inventory and adapter-specific tests, but not reaper logic.

Discovery results:

- No adapters: safe no-op.
- No active adapters: safe no-op.
- Exactly one active, valid adapter: validate its candidate.
- More than one active adapter: ambiguous environment; safe no-op.
- Any active adapter emits malformed or unsafe output: safe no-op.

The core never applies platform precedence. A nested environment exposing multiple harness session markers is ambiguous rather than permission to choose one.

## Adapter Protocol

### Invocation

The core executes each adapter with no arguments. Adapters are trusted packaged code, but their output is treated as untrusted data because bugs in path construction must fail closed.

### Exit statuses

| Status | Meaning | Core behavior |
|---|---|---|
| `0` | Active adapter; descriptor emitted | Parse and consider descriptor |
| `3` | Adapter is inactive | Ignore adapter |
| Any other status | Active state is invalid or resolution failed | Emit diagnostic and no-op the entire sweep |

An adapter that recognizes its native marker but finds a missing, malformed, ambiguous, or unsupported scratch target returns a non-zero status other than `3`. This distinguishes "not this platform" from "this platform, but cleanup cannot be proven safe."

### Descriptor format

A successful adapter emits UTF-8 text with one field per line:

```text
SWB_SESSION_SCRATCH_V1
<adapter-id>
<absolute-authorized-root>
<candidate-count>
<relative-candidate-1>
...
```

Rules:

- The protocol marker must match exactly.
- Adapter IDs match `^[a-z0-9][a-z0-9-]*$` and are diagnostic only.
- The authorized root is absolute.
- Candidate count is a non-negative decimal integer and equals the number of following records.
- Candidate paths are relative and contain neither empty, `.` nor `..` components.
- Dynamic fields containing carriage return or newline are rejected by the adapter before emission.
- The core parses records as data. It never uses `eval`, `source`, or shell expansion on descriptor content.
- Extra or missing records invalidate the entire descriptor.

Newline-containing POSIX paths are unsupported and produce a safe no-op. This explicit limitation keeps the Bash protocol auditable without introducing encoded payloads or a second parser dependency.

## Generic Safety Policy

After selecting one descriptor and one relative candidate, the core applies all checks below.

### Authorized root

- Must be absolute.
- Must not be `/`.
- Must exist and be a directory.
- Must not itself be a symlink.
- Must be owned by the current effective user.
- Must canonicalize successfully.

### Relative candidate

- Must contain at least two path components so the authorized root itself or its immediate child can never become the sweep target.
- Must not start with `/`.
- Must not contain empty, `.` or `..` components.
- Must resolve from the authorized root without shell evaluation.
- Every existing component from the authorized root through the target must not be a symlink.

### Canonical target

- Must canonicalize successfully.
- Must remain a strict descendant of the canonical authorized root.
- Must exist and be a directory.
- Must not be a symlink.
- Must be owned by the current effective user.
- Must not contain a top-level `.git` entry.
- Must still satisfy the same canonical-root relationship immediately before removal begins.

### Removal

- Enable `nullglob` and `dotglob` only around candidate enumeration and removal as needed.
- Remove each top-level entry with `rm -rf --`.
- Increment `SWEPT_SESSION_FILES` only after an entry is removed successfully.
- Warn and leave an entry in place when its removal fails.
- Never remove the target directory.
- Always emit exactly one `SWEPT_SESSION_FILES=<n>` assignment and exit zero.

The adapter chooses what may be considered; the core decides whether it is safe enough to remove.

## Initial Adapters

### Claude Code

The Claude adapter preserves the current contract:

- Active marker: non-empty `CLAUDE_CODE_SESSION_ID`.
- Session-ID grammar: current 36-character hexadecimal-and-hyphen validation, unchanged for compatibility.
- Authorized root: `/tmp/claude-<uid>`, accounting for the platform's canonical `/tmp` spelling.
- Native candidate shape: `<project>/<session-id>/scratchpad`.
- Exactly one glob match is required.
- The adapter reports the candidate relative to the authorized root.

Claude-specific tests retain zero-hit, multiple-hit, malformed-ID, decoy-name, and native path-shape coverage. Generic symlink, ownership, `.git`, count, preservation, and idempotence cases move to core contract tests.

### Pi Coding Agent

The Pi adapter:

- Detects `PI_SESSION_ID` as the native session marker.
- Validates that the marker is non-empty and contains no control characters.
- Does not infer a scratch target from `PI_SESSION_FILE`, `PI_CODING_AGENT_SESSION_DIR`, `--session-dir`, or the documented JSONL session location.
- Does not reuse Claude's `/tmp/claude-<uid>` namespace.
- Reports an unsupported-resolution diagnostic and returns a failing active-adapter status, causing `SWEPT_SESSION_FILES=0`.

Pi 0.84.2 documents `PI_SESSION_ID`, optional `PI_SESSION_FILE`, configurable session storage, and JSONL session files. It does not document or create a sanctioned session scratch directory. Retention is therefore the only safe initial behavior.

When Pi introduces a sanctioned scratch contract, or swe-workbench separately adopts an owned scratch-writing lifecycle, only the Pi adapter and its adapter tests/documentation change. The core and cleanup workflow remain unchanged.

## Error Handling

The script remains best-effort cleanup and always exits zero. Diagnostics go to stderr; the machine-readable count goes to stdout.

| Condition | Result |
|---|---|
| No active platform | Zero-count no-op |
| Multiple active platforms | Zero-count no-op with ambiguity diagnostic |
| Invalid native session ID | Zero-count no-op |
| Unsupported native scratch contract | Zero-count no-op |
| Malformed adapter descriptor | Zero-count no-op |
| Zero or multiple candidates | Zero-count no-op |
| Unsafe root or target | Zero-count no-op |
| Target disappears before removal | Zero-count no-op |
| One entry fails removal | Continue with remaining entries; count only successes |

No adapter failure may abort `workflow-cleanup-merged` or suppress the required count assignment.

## Testing Strategy

### Core contract tests

Refactor `tests/test_reap_session_scratch.py` to execute a copied core from an isolated temporary `bin/` containing explicit fake adapters. These tests use neutral names and paths and cover:

- No adapters, inactive adapters, and one active adapter.
- Multiple active adapters.
- Adapter failure and malformed descriptors.
- Descriptor version, field count, candidate count, absolute-root, and relative-path validation.
- Zero and multiple candidates.
- Root, intermediate-component, and target symlinks.
- Root escape and canonical-root mismatch.
- Missing, non-directory, and foreign-owned targets.
- Top-level `.git` rejection.
- Hidden entries, top-level counting, directory preservation, and idempotence.
- Partial removal failure counting.
- Exactly one output assignment and exit-zero behavior.

Use pytest fixtures and parameterization for repeated malformed-input cases. Invoke subprocesses with argument lists and explicit environments; never use `shell=True`.

### Adapter tests

Add a separate test module for adapter contracts. Each platform receives focused tests for:

- Active and inactive detection.
- Native ID grammar.
- Native root and relative candidate shape.
- Zero and ambiguous candidates.
- Rejection of line-breaking values.
- Descriptor protocol compliance.

The Claude adapter gets a successful-resolution fixture. The Pi adapter verifies active-but-unsupported behavior and confirms that `PI_SESSION_FILE` cannot authorize a target.

### Environment isolation

`tests/conftest.py` strips both `CLAUDE_CODE_SESSION_ID` and `PI_SESSION_ID` from `_CLEAN_ENV`. Core tests additionally isolate adapter discovery by copying only explicitly selected fake adapters beside the copied core. Tests that need a native session marker opt in with a fake value.

A future adapter must add its native marker to the clean-environment denylist and its own adapter tests. That is adapter integration work, not a cleanup-core change.

### Regression commands

Implementation verification will include:

```bash
python3 -m pytest tests/test_reap_session_scratch.py tests/test_session_scratch_adapters.py -q
python3 -m pytest -q
bash -n bin/swe-workbench-reap-session-scratch bin/swe-workbench-session-scratch-adapter-*
```

If available, run ShellCheck against the changed Bash scripts.

## Documentation Changes

- `bin/README.md`: describe the platform-neutral core, adapter naming convention, and fail-closed protocol.
- `skills/workflow-cleanup-merged/SKILL.md`: replace Claude-specific resolution wording with the generic adapter contract and document ambiguous/unsupported platform behavior.
- Pi documentation notes: state that Pi provides session metadata but no sanctioned scratch target in the supported version.
- Script headers: keep the reaper header platform-neutral; place native path details in each adapter header.

## Packaging and Validation

The existing npm package includes `bin/swe-workbench-*`, so sibling adapter executables are shipped without a new directory glob. Update the repository's bin inventory tests for the two new commands and require executable Bash shebangs and syntax checks.

The reaper resolves adapters from its own directory, not `PATH`, the current working directory, a user-controlled environment override, or `$CLAUDE_PLUGIN_ROOT`.

## Reversibility

- Removing a platform adapter disables that platform without changing the core.
- Replacing a native path contract changes only one adapter.
- The Claude adapter can be rolled back to the original inline logic if adapter discovery causes an unforeseen packaging issue.
- The protocol is versioned so an incompatible descriptor change can be introduced without silently reinterpreting old output.

## Risks and Signals

- **Pi remains a no-op:** expected until a sanctioned scratch contract exists. Watch Pi release notes and extension APIs for an explicit scratch location.
- **Multiple ambient harness markers:** the reaper intentionally no-ops. Watch ambiguity diagnostics in nested-agent environments.
- **Adapter path drift:** watch zero-candidate diagnostics and adapter contract tests after harness upgrades.
- **Over-broad adapter root:** generic ownership, strict-descendant, component-depth, symlink, and canonicalization checks limit blast radius; review adapter roots as security-sensitive constants.
- **TOCTOU replacement:** keep roots user-owned and narrow; investigate intermittent removal failures rather than weakening checks.
- **Adapter proliferation:** retain executable discovery while adapters remain small. Do not add a registry or framework until concrete duplication from at least a third functional adapter justifies it.
