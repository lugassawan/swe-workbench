---
description: Record a cross-harness memory entry (correction, gotcha, or project fact) into the current harness's per-repo memory store.
argument-hint: "<entry name> — <one-line description>"
---

The user wants to record a per-repo memory entry: $ARGUMENTS

**Preflight (run once):**

```bash
command -v swe-workbench-memory >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
```

**Harness detection (run once, before any record):** do not probe `PATH` — both
CLIs can be installed while only one is running. Use the session env var each
harness injects into its own bash tool:

```bash
[ -n "${PI_SESSION_ID:-}" ] && echo pi || echo claude
```

The result is `$HARNESS` (`pi` or `claude`) — the store the entry is written to.
Each harness owns exactly one store; the other's is read-only by construction.

**Derive the entry fields** from `$ARGUMENTS` and the conversation:

- `--name` — short identity for the entry (no square brackets; ≤ 200 bytes).
- `--description` — one-line summary of the lesson or fact (≤ 1000 bytes).
- `--type` — `feedback` (correction, gotcha, "don't do this again") or `project`
  (project history, decision, outcome). Pick the closer fit.
- body — the full context: what happened, why it matters, the rule going
  forward. ≤ 12 000 bytes; oversized input is refused, never silently truncated.

**Write the body to a temp file with the Write tool** (never carry free text
through a shell variable): obtain `BODY_FILE=$(mktemp)`, write the body there,
then record:

```bash
RESULT=$(swe-workbench-memory record --as "$HARNESS" \
  --name "$NAME" --description "$DESCRIPTION" --type "$TYPE" \
  --body-file "$BODY_FILE" \
  | swe-workbench-result-check swb.memory/1) || exit 1
printf '%s' "$RESULT" | jq -r '"Recorded: " + .data.entry_path'
swe-workbench-clean-state-files "$BODY_FILE" 2>/dev/null
```

On a refusal (non-zero exit, message on stderr): the runtime names the refused
field and why — secret-shaped input, length cap, bracketed name. Shorten or
redact per the message and retry **once**; a second refusal is surfaced to the
user verbatim, not worked around.

Confirm to the user with the recorded entry path. Never write to the other
harness's store — there is no flag that can, by design.
