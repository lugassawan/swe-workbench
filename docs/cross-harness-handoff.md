# Cross-harness handoff (Claude Code ↔ Pi)

Seamless handoff of in-flight work between Claude Code and Pi **in the same git worktree**,
designed around quota exhaustion: hand off before you run out, recover truthfully after you
have. One command surface (`commands/handoff.md` → `/swe-workbench:handoff` on Claude Code,
`/handoff` on Pi) and one harness-neutral runtime (`bin/swe-workbench-handoff`) own the whole
protocol; the adapters only translate events.

## Model

A handoff is a **bounded semantic checkpoint** — goal, constraints, decisions, progress,
changed-path intents, bounded verification outcomes, blockers, risks, and one
`exact_next_action`. Native session transcripts are never exported, copied, or
reconstructed: the formats are mutually unreadable, and transcripts carry content this
protocol deliberately excludes (patches, file bodies, environment values, credentials,
arbitrary messages). The receiver re-reads the live worktree — the checkpoint tells it what
to look at, not what the files said.

Ownership is a **lease** on the worktree, keyed by repository and worktree:

- After `create`, the lease is `released` — only the target harness may acquire it.
- `resume` binds the lease to a receiver session; the source harness (and every other
  session) is blocked from mutating until the handoff is closed.
- `close` (owner-authenticated) ends the lease and returns the worktree to normal.

The **source harness must stop mutating after `create`** — this is enforced, not advisory:
Claude's PreToolUse hook (`hooks/handoff_guard.py`) and Pi's native adapter
(`pi/extensions/handoff.ts`) block `Bash`/`Edit`/`Write` (Pi: `bash`/`write`/`edit`) while a
lease they do not own is in flight, allowing only the exact anchored lifecycle pipelines
(resume/recover with a literal `--receiver-session-env`/`--source-stopped` and a
`| swe-workbench-result-check swb.handoff/1` tail — every pipeline argument is a literal
value, never a runtime `${VAR}` shell expansion). Blocking messages carry the exact receiver
command and the leased worktree path, e.g. ``run `/handoff resume <id>` in the receiver``
plus the worktree root the guard resolved the lease against — so a session that finds itself
blocked can tell which worktree holds the lease even when it differs from its own.

## Routes

- **Planned** — `/swe-workbench:handoff pi` (or `claude`): writes the semantic JSON to a
  private `mktemp` file via the Write tool (never through a shell variable), pipes it into
  `swe-workbench-handoff create < file`, validates the `swb.handoff/1` envelope, prints the
  receiver instruction, and **stops**.
- **resume** — the receiver acquires ownership:
  `swe-workbench-handoff resume <id> --as <harness> --receiver-session-env PI_SESSION_ID`
  (Claude: `CLAUDE_CODE_SESSION_ID`), then `show` to present the checkpoint. Session refs are
  required and bounded; a session-less resume is rejected rather than binding an unbound lease.
- **recover** — after the source harness has *hard-failed* (quota exhaustion, crash): the
  receiver runs `swe-workbench-handoff recover --from <source> --source-stopped`. The literal
  `--source-stopped` flag is the acknowledgement that the source is truly stopped.
  Recovery is **truthful degraded salvage**: it rebuilds from the prior checkpoint (if any)
  plus deterministic git evidence only, marks the checkpoint `degraded`, and requires
  `--acknowledge-degraded` on resume before ownership is granted.
- **close** — owner-authenticated (`--as` + `--session-ref-env` matching the lease); closes the
  checkpoint and removes the lease.

### Abandoning a checkpoint

The guard mediates the *agent's* tools (`Bash`/`Edit`/`Write` on Claude, `bash`/`write`/`edit`
on Pi) — it does not, and cannot, stop a human operator from running the runtime directly in a
plain shell. If a checkpoint needs to be walked back (a lease left `released` with no live
receiver, an abandoned salvage attempt), an operator can resume and immediately close it:

```bash
swe-workbench-handoff resume <id> --as <target> --receiver-session <ref>
swe-workbench-handoff close <id> --as <same-target> --session-ref <same-ref>
```

Three sharp edges apply, all enforced by the runtime itself:

- `--as` must match the checkpoint's `target_harness` exactly; resuming with the wrong harness
  is rejected before any lease state changes.
- A `degraded` (salvage) checkpoint requires `--acknowledge-degraded` on the `resume` call, or
  it is refused.
- `resume` refuses if the live worktree has drifted since the checkpoint was written (its
  dirty fingerprint no longer matches). That is not itself abandonable — the path is
  `swe-workbench-handoff recover --from <source> --source-stopped`, which rebuilds a fresh,
  honestly `degraded` checkpoint from the current worktree instead of trusting stale state.

Stale-checkpoint and lease-identity mismatches are rejected on both `resume` and `close`,
so an old checkpoint id can never rebind or release a newer handoff's lease.

## State and retention

State lives under `${XDG_STATE_HOME:-$HOME/.local/state}/swe-workbench/handoff/v1`, keyed by
repository and worktree, never inside the repo (no accidental commits, no repo hygiene
cost). `SWE_WORKBENCH_HANDOFF_STATE_DIR` overrides the root for tests. Checkpoints expire
after 7 days; consumed/closed ones after 24 hours. The active lease's checkpoint is always
retained. Cleanup is opportunistic on lifecycle commands — never a background daemon. State
is private to the machine; nothing is pushed anywhere.

## Quota warnings (asymmetric by design)

- **Claude** has exact five-hour subscription quota fields. Compose them into your status
  line with `swe-workbench-handoff status-segment`: it reads Claude's statusline JSON on
  stdin, prints nothing below 80%, `handoff available` at 80–89%, and — once — records an
  urgent notice and prints `handoff urgent: create a checkpoint now` at ≥90%.
- **Pi** has no trustworthy subscription-quota signal (context-window usage is **not**
  quota), so Pi warns only after an actual **HTTP 429**: the extension sets a persistent
  footer status and one warning per session with the exact recovery command
  (`swe-workbench-handoff recover --from pi --source-stopped | swe-workbench-result-check
  swb.handoff/1`). Repeated 429s never spam.

## Failure postures

Missing runtime install fails **open** with a one-time warning (a broken plugin install must
not deadlock every mutation); everything else — spawn error, timeout, corrupt lease/checkpoint
state, undecidable output — fails **closed**. Malformed notices state is fatal, never
swallowed. Active leases are always session-bound; a malformed or unbound active lease is
treated as corrupt.

## Result contract

Every runtime invocation is validated through `swe-workbench-result-check swb.handoff/1`
(`shared/docs/runtime-result-contract.md`). Subcommands share the schema and return
command-specific `data`; recovery returns `status: partial` with a `degraded_recovery`
warning rather than claiming parity.

## Security exclusions (hard constraints)

Never in handoff state: native transcripts, environment values, credentials, arbitrary
messages, raw tool output, patches, or file bodies. Checkpoint fields are bounded in size and
shape; verification entries are `{command, label, exit_status, timestamp, result}` with a
bounded result only. Salvage recovery uses git status, untracked-file hashes, and prior
structured fields — it never shells out to reconstruct content.
