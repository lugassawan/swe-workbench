---
description: Hand work to Claude Code or Pi through a bounded semantic checkpoint, resume or recover a checkpoint, inspect status, or close a completed handoff.
---

Manage a Claude Code ↔ Pi handoff in the current git worktree. Parse `$ARGUMENTS` as exactly one of:

- `pi [--next "<exact next action>"]` or `claude [--next "<exact next action>"]` — create a planned handoff to that harness.
- `resume <checkpoint-id> [--acknowledge-degraded]` — acquire and continue a checkpoint in the current harness.
- `recover --from <claude|pi> --source-stopped` — salvage deterministic workspace state after the source harness has stopped unexpectedly.
- `close <checkpoint-id>` — end the lease and retain the closed checkpoint for normal cleanup.

Reject any other arguments with a short usage message.

## Preflight

Run once before planned checkpoint creation. Resume, recovery, and close use the exact single-pipeline forms below because the ownership hook permits only those lifecycle commands through an active or released lease:

```bash
command -v swe-workbench-handoff >/dev/null 2>&1 || {
  echo "swe-workbench handoff runtime is not on PATH — reinstall or update the plugin." >&2
  exit 1
}
command -v swe-workbench-result-check >/dev/null 2>&1 || {
  echo "swe-workbench result checker is not on PATH — reinstall or update the plugin." >&2
  exit 1
}
```

Never export, copy, summarize from, or persist a native Claude/Pi transcript. Never include environment values, credentials, arbitrary messages, raw tool output, patches, or file bodies in handoff state.

## Planned handoff: `pi` or `claude`

1. Build one JSON object with this exact top-level shape:

   ```json
   {
     "operation_id": "new UUID",
     "source_harness": "claude or pi",
     "target_harness": "pi or claude",
     "source_session_ref": "current session reference when known",
     "semantic": {
       "goal": "bounded summary",
       "constraints": ["bounded strings"],
       "decisions": ["bounded strings"],
       "progress": {"done": ["bounded strings"], "in_progress": ["bounded strings"]},
       "changed_path_intents": {"relative/path": "intent only, never content"},
       "verification": [{"command": "bounded command", "label": "bounded label", "exit_status": 0, "timestamp": "ISO-8601 timestamp", "result": "bounded status"}],
       "blockers": ["bounded strings"],
       "risks": ["bounded strings"],
       "exact_next_action": "one executable next action"
     }
   }
   ```

   Use the `--next` value verbatim as `exact_next_action` when supplied. Determine `source_harness` as `pi` when `PI_SESSION_ID` is set and `claude` otherwise. For Pi, use `PI_SESSION_ID` as `source_session_ref`; for Claude, use `CLAUDE_CODE_SESSION_ID`. Describe only facts supported by the current task and workspace. Omit `source_session_ref` when unknown.

2. Create a private temporary file with `mktemp`, register cleanup immediately, and use the Write tool to write only that JSON object to `$HANDOFF_INPUT`. Do not put the JSON in a shell variable, command argument, echo, heredoc, or log.

   ```bash
   HANDOFF_INPUT=$(mktemp)
   trap 'rm -f "$HANDOFF_INPUT"' EXIT INT TERM
   # Use the Write tool to write the semantic JSON to $HANDOFF_INPUT.
   HANDOFF_RESULT=$(swe-workbench-handoff create < "$HANDOFF_INPUT" \
     | swe-workbench-result-check swb.handoff/1) || exit 1
   rm -f "$HANDOFF_INPUT"
   trap - EXIT INT TERM
   printf '%s\n' "$HANDOFF_RESULT"
   ```

3. Read `data.checkpoint_id`, `data.target_harness`, and `data.worktree_root` from the validated envelope. Print the appropriate exact receiver command:

   - Pi: `cd <worktree-root> && /handoff resume <checkpoint-id>`
   - Claude Code: `cd <worktree-root> && /swe-workbench:handoff resume <checkpoint-id>`

4. Print: **`STOP: the source harness must not mutate this worktree after checkpoint creation; continue only in the receiver.`** Then stop. Do not run another mutating tool. The ownership hook enforces this invariant.

## Resume

Determine the current harness (`pi` when `PI_SESSION_ID` is set; otherwise `claude`). Bind the lease to the canonical receiver session: Pi uses `PI_SESSION_ID`; Claude uses `CLAUDE_CODE_SESSION_ID`, which matches the Claude hook payload identity. A missing session ID is an error; never acquire an unbound lease.

Run exactly one of these single pipelines, inserting `--acknowledge-degraded` only when explicitly requested:

```bash
# Claude receiver
swe-workbench-handoff resume "<checkpoint-id>" --as claude \
  --receiver-session "${CLAUDE_CODE_SESSION_ID:?missing CLAUDE_CODE_SESSION_ID}" \
  <include --acknowledge-degraded only when requested> \
  | swe-workbench-result-check swb.handoff/1

# Pi receiver
swe-workbench-handoff resume "<checkpoint-id>" --as pi \
  --receiver-session "${PI_SESSION_ID:?missing PI_SESSION_ID}" \
  <include --acknowledge-degraded only when requested> \
  | swe-workbench-result-check swb.handoff/1
```

After ownership is acquired, run `swe-workbench-handoff show "<checkpoint-id>" | swe-workbench-result-check swb.handoff/1`. Read and present the bounded checkpoint fields: goal, constraints, decisions, progress, changed-path intents, verification status, blockers, risks, and exact next action. Verify the displayed worktree root matches the current worktree. For a degraded checkpoint, do not proceed unless `--acknowledge-degraded` was explicitly supplied. Continue from `exact_next_action` in the same worktree; do not import a native session history.

## Recover

Require both `--from <claude|pi>` and the literal `--source-stopped` acknowledgement. Then run:

```bash
swe-workbench-handoff recover --from "<source-harness>" --source-stopped \
  | swe-workbench-result-check swb.handoff/1
```

Print the returned checkpoint id and warning. Recovery is truthful degraded salvage from git/worktree evidence, not semantic reconstruction. Tell the user to resume the returned checkpoint with explicit `--acknowledge-degraded` in the receiver.

## Close

Run the exact lifecycle pipeline:

```bash
swe-workbench-handoff close "<checkpoint-id>" \
  | swe-workbench-result-check swb.handoff/1
```

Do not claim a handoff completed until `close` returns a validated `status: ok` envelope. The `status-segment` runtime subcommand is reserved for Claude status-line quota composition and is not an interactive handoff route.
