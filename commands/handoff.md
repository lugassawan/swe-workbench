---
description: Hand work to Claude Code or Pi through a bounded semantic checkpoint, resume or recover a checkpoint, inspect status, or close a completed handoff.
---

Manage a Claude Code ↔ Pi handoff in the current git worktree. Parse `$ARGUMENTS` as exactly one of:

- `pi [--next "<exact next action>"]` or `claude [--next "<exact next action>"]` — create a planned handoff to that harness.
- `resume <checkpoint-id> [--acknowledge-degraded]` — acquire and continue a checkpoint in the current harness.
- `recover --from <claude|pi> --source-stopped` — salvage deterministic workspace state after the source harness has stopped unexpectedly.
- `close <checkpoint-id>` — end the lease and retain the closed checkpoint for normal cleanup.
- `status` — print the latest checkpoint and lease state without changing them.

Reject any other arguments with a short usage message.

## Preflight

Run once before every route:

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
       "verification": [{"command": "command name only", "result": "bounded status"}],
       "blockers": ["bounded strings"],
       "risks": ["bounded strings"],
       "exact_next_action": "one executable next action"
     }
   }
   ```

   Use the `--next` value verbatim as `exact_next_action` when supplied. Describe only facts supported by the current task and workspace. Omit `source_session_ref` when unknown.

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

3. Read `data.checkpoint_id`, `data.target_harness`, and `data.instruction` from the validated envelope. Print the instruction and the appropriate exact receiver command:

   - Pi: `cd <worktree-root> && /handoff resume <checkpoint-id>`
   - Claude Code: `cd <worktree-root> && /swe-workbench:handoff resume <checkpoint-id>`

4. Print: **`STOP: the source harness must not mutate this worktree after checkpoint creation; continue only in the receiver.`** Then stop. Do not run another mutating tool. The ownership hook enforces this invariant.

## Resume

Determine the current harness (`pi` when `PI_SESSION_ID` is set; otherwise `claude`). Bind the lease to a receiver session. Pi must use `PI_SESSION_ID`; Claude may use `CLAUDE_SESSION_ID` when available, otherwise a stable local fallback that contains no environment value or credential:

```bash
SESSION_REF="${PI_SESSION_ID:-${CLAUDE_SESSION_ID:-claude-local}}"
HANDOFF_RESULT=$(swe-workbench-handoff resume "<checkpoint-id>" \
  --as "<current-harness>" --receiver-session "$SESSION_REF" \
  <include --acknowledge-degraded only when requested> \
  | swe-workbench-result-check swb.handoff/1) || exit 1
printf '%s\n' "$HANDOFF_RESULT"
```

Read and present the bounded checkpoint fields from the validated envelope: goal, constraints, decisions, progress, changed-path intents, verification status, blockers, risks, and exact next action. Verify the displayed worktree root matches the current worktree. For a degraded checkpoint, do not proceed unless `--acknowledge-degraded` was explicitly supplied. Continue from `exact_next_action` in the same worktree; do not import a native session history.

## Recover

Require both `--from <claude|pi>` and the literal `--source-stopped` acknowledgement. Then run:

```bash
HANDOFF_RESULT=$(swe-workbench-handoff recover --from "<source-harness>" --source-stopped \
  | swe-workbench-result-check swb.handoff/1) || exit 1
printf '%s\n' "$HANDOFF_RESULT"
```

Print the returned checkpoint id and warning. Recovery is truthful degraded salvage from git/worktree evidence, not semantic reconstruction. Tell the user to resume the returned checkpoint with explicit `--acknowledge-degraded` in the receiver.

## Close or status

For close:

```bash
swe-workbench-handoff close "<checkpoint-id>" \
  | swe-workbench-result-check swb.handoff/1
```

For status, run `swe-workbench-handoff status` and print its JSON unchanged. Status is read-only. Do not claim a handoff completed until `close` returns a validated `status: ok` envelope.
