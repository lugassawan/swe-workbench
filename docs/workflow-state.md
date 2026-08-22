# Workflow state persistence

When Claude Code auto-compacts a long conversation, any in-progress swe-workbench
workflow state lives only in the model's working context and is silently dropped.
Auto-compaction happens precisely on large, complex tasks — exactly where these workflows
matter most — leaving the user mid-flight with no clean way to resume.

Workflow state persistence externalizes that state to a sidecar JSON file written by the
model at each phase/step boundary, and re-injects a resume preamble after compaction so
the workflow continues at the correct step.

## How it works

### State file

| Property | Value |
|---|---|
| **Path** | `<git-toplevel>/.claude/cache/workflow-state/<branch-with-slashes-as-dashes>.json` |
| **Example** | `.claude/cache/workflow-state/feature-286-workflow-state-persistence.json` |
| **Directory** | `.claude/cache/` — the plugin's ephemeral-state home |

Consumer repos must add `.claude/cache/` to their own `.gitignore` — the plugin has no way
to write it for you. `/swe-workbench:doctor` checks for this at doctor time (a **Repo
hygiene** section warns if the directory is not gitignored, or if anything under it is
already tracked) but never edits `.gitignore` or runs `git rm` itself.

Both the model (writer) and the hook (reader) resolve the git toplevel via
`git rev-parse --show-toplevel` from the session's cwd. This means the path agreement
holds whether the session runs in the main checkout or a linked worktree.

Per-branch filenames give worktree isolation for free: two worktrees on the same repo
but different branches never share a checkpoint file.

### Schema

```json
{
  "version": 1,
  "skill": "swe-workbench:workflow-development",
  "mode": "B",
  "phase": "3",
  "phase_label": "Verify",
  "completed_phases": ["1", "2"],
  "context": {
    "branch": "feature/286-workflow-state-persistence",
    "worktree_root": "/abs/path/to/worktree",
    "pr": null,
    "base": null,
    "head_sha": null,
    "decision": null,
    "notes": "free-form key decisions / identifiers"
  },
  "updated_at": "2026-05-21T10:30:00Z"
}
```

- `version` — schema version; the hook ignores files with unknown versions (fail-soft).
- `skill` — fully-qualified skill name driving the workflow.
- `mode` — optional mode letter (A/B/C for workflow-development; absent for single-mode skills).
- `phase` / `phase_label` — current phase/step number and human label; `completed_phases` lists all finished phases.
- `context` — flat free-form bag; `context.branch` is the resume-validation key. Skills pack skill-specific values here (`pr`, `head_sha`, `decision` for pr-review; project-detection values for workflow-development). `context.worktree_root` records the absolute path of the worktree where the session is doing its work — populate it with `git rev-parse --show-toplevel` at Phase 1 checkpoint, or omit it when working in the main checkout.
- `updated_at` — ISO-8601 timestamp (informational — not used for staleness; the hook uses filesystem mtime instead).

**Coverage limit for the worktree re-anchor nudge:** As of issue #497, the nudge fires independently of the sidecar gate: it probes `git rev-parse --git-dir --git-common-dir` directly and fires whenever cwd resolves to a linked worktree — including the *same-path* case (a fresh sidecar's `worktree_root` already matches the live root) and the *sidecar-less* case (no checkpoint exists at all, e.g. a workflow that never wrote one). Only when cwd is **not** a linked worktree does the hook stay silent. As of issue #524, the hook also fires on `startup` (cold launch) and `resume` (`--continue`/`--resume`/`/resume`), not only `compact` — closing the gap where a non-compaction session resume left `EnterWorktree` tracking silently unrecovered. Wording is source-aware: a `startup`/`resume` firing never claims "this session was compacted" (see `context.worktree_root` note below and the Hook registration table). Two intentional gaps remain: `clear` (`/clear`) is not covered, since anchoring generally survives it (same process, same cwd); and the hook still **cannot** redirect to a *foreign* worktree it has no checkpoint for (e.g. a session that was always anchored in the wrong dir) — path mismatch still only produces the `REQUIRED` variant when a sidecar records a differing `worktree_root`. The worktree_root nudge is defense-in-depth; the primary guidance lives in `skills/workflow-worktree-session/SKILL.md` and the plan template.

### Lifecycle

| Actor | Event | Action |
|---|---|---|
| **Model** | Phase/step transition | Write (overwrite) the state file with the new phase |
| **Model** | Terminal phase success | Delete the state file |
| **Hook** | SessionStart(startup\|resume\|compact) | Read the file; inject resume preamble if fresh + valid |
| **Hook** | SessionStart(startup\|resume\|compact), file >24h old | Delete the file; no injection (staleness sweep) |
| **Hook** | SessionStart(startup\|resume\|compact), branch mismatch or version ≠ 1 | No injection (fail-open, file untouched) |

The state file is a **fail-soft cache, not a source of truth**. The model owns the semantic
lifecycle (write/delete at phase boundaries). The hook owns the mechanical lifecycle
(detect-and-inject, age-sweep). The hook never reconstructs state — any ambiguity degrades
to "ask", because a wrong resume is worse than no resume.

### Hook registration

| Event | Matcher | Script |
|---|---|---|
| `SessionStart` | `"startup"` | `hooks/workflow_resume_hint.sh` |
| `SessionStart` | `"resume"` | `hooks/workflow_resume_hint.sh` |
| `SessionStart` | `"compact"` | `hooks/workflow_resume_hint.sh` |

`SessionStart` requires a `matcher` string (not a lifecycle event in `validate.py`); each
matcher is registered as its own explicit single-matcher entry (rather than one piped
`"startup|resume|compact"` entry) so a silent non-match on unsupported piped-matcher
regex support would be visible rather than invisible. Together the three matchers cover
cold launch (`startup`), continuation via `--continue`/`--resume`/`/resume` (`resume`),
and auto-compaction (`compact`). `"clear"` (`/clear`) is intentionally not registered —
`/clear` keeps the same process and cwd, so `EnterWorktree` anchoring generally survives
it. The injected wording is conditioned on the SessionStart `.source` field (see
`hooks/workflow_resume_hint.sh`'s `set_framing`) so a `startup`/`resume` firing never
falsely claims "this session was compacted".

The hook always exits 0 — it never blocks session startup.

### On the Pi Coding Agent

`pi/extensions/guards.ts` registers the same unchanged `hooks/workflow_resume_hint.sh` script on
Pi's `session_start` and `session_compact` events. The three-way `startup`/`resume`/`compact`
distinction survives as an event-to-source mapping rather than three separate hook registrations:
`cc-payload.ts`'s `sessionStartSource()` maps Pi's `session_start` event `.reason` field
(`startup`/`new` → `"startup"`, `resume`/`reload`/`fork` → `"resume"`) onto the same `.source`
vocabulary the script already reads, and `sessionCompactSource()` always maps `session_compact`
to `"compact"`. The script itself is invoked unmodified via `guard-runner.ts`'s `exec`; a non-empty
result is then delivered via `pi.sendMessage({ customType: "swe-workbench:workflow-resume-hint",
... }, { deliverAs: "nextTurn" })` rather than Claude Code's `hookSpecificOutput.additionalContext`
— same resume preamble content and source-aware wording, different delivery mechanism, since Pi
has no additional-context hook return shape.

## What survives compaction and what doesn't

| Information | Survives? | Why |
|---|---|---|
| Current phase and phase label | ✓ | Written to state file at each transition |
| Completed phases list | ✓ | Written to state file at each transition |
| Skill name and mode | ✓ | Written to state file on entry |
| PR number, base, HEAD SHA, decision | ✓ | Packed into `context` by pr-review skill |
| Free-form notes and key decisions | ✓ | Model writes to `context.notes` |
| Full conversation history | ✗ | Compaction by design; the preamble is not a replay |
| Uncommitted code changes | ✗ | Live in the worktree filesystem — unaffected by compaction |
| Sub-skill internal state | ✗ | Each sub-skill manages its own context |
| Harness `EnterWorktree` session anchoring | ✗ | Harness-owned, external to this sidecar — the plugin cannot make it persist. This is the root cause of issue #497's `ExitWorktree action=keep` no-op: the Bash cwd stays inside the worktree, but the harness's own tracking of the `EnterWorktree` session can be silently dropped by compaction. Mitigation: `context.worktree_root` plus the resume-hook re-anchor nudge (see Coverage limit above) and the ambiguity-aware Mode C diagnostic in `skills/workflow-worktree-session/SKILL.md`. |

## Manual smoke test

```bash
# 1. Create a minimal state file for the current branch
BRANCH=$(git branch --show-current)
SAFE="${BRANCH//\//-}"
STATEDIR="$(git rev-parse --show-toplevel)/.claude/cache/workflow-state"
mkdir -p "$STATEDIR"
python3 -c "
import json, sys
s = json.loads(sys.stdin.read())
s['context']['branch'] = sys.argv[1]
print(json.dumps(s))
" "$BRANCH" <<'EOF' > "$STATEDIR/${SAFE}.json"
{
  "version": 1,
  "skill": "swe-workbench:workflow-development",
  "mode": "B",
  "phase": "2",
  "phase_label": "Implement",
  "completed_phases": ["1"],
  "context": { "branch": "BRANCH_PLACEHOLDER", "worktree_root": null, "notes": "smoke test" },
  "updated_at": "2026-05-21T00:00:00Z"
}
EOF

# 2. Run the hook with a simulated SessionStart payload
echo '{"cwd":"'"$(git rev-parse --show-toplevel)"'"}' \
  | bash hooks/workflow_resume_hint.sh

# Expected: JSON with hookSpecificOutput.additionalContext containing the skill name and phase.
# No .source field → neutral wording ("[Workflow auto-resume]" / "This session resumed.").

# 2b. Reproduce each source-aware framing by adding a `.source` field.
# `source` selects the wording: compact | resume | startup | (absent/other → neutral).
for src in compact resume startup; do
  echo "--- source=$src ---"
  jq -cn --arg cwd "$(git rev-parse --show-toplevel)" --arg source "$src" \
    '{cwd: $cwd, source: $source}' \
    | bash hooks/workflow_resume_hint.sh \
    | jq -r '.hookSpecificOutput.additionalContext' | head -3
done

# Expected headers, respectively:
#   [Workflow auto-resume after compaction]   / "This session was compacted."
#   [Workflow auto-resume after continuation] / "This session was resumed/continued."
#   [Workflow auto-resume on startup]         / "This is a fresh session start."
# None but the `compact` case may contain the word "compacted". The startup intro is
# worktree-agnostic by design — the worktree-specific claim (is this cwd a linked
# worktree?) belongs to the separately gated reanchor_line/format_advisory, not the intro.

# 3. Test the no-op path (no file)
rm "$STATEDIR/${SAFE}.json"
echo '{"cwd":"'"$(git rev-parse --show-toplevel)"'"}' \
  | bash hooks/workflow_resume_hint.sh

# Expected: empty output, exit 0.
```

## Troubleshooting

**Hook fires but no preamble is injected:**

- Confirm the state file exists: `ls .claude/cache/workflow-state/`.
- Confirm the branch name in `context.branch` matches `git branch --show-current` exactly.
- Confirm `"version": 1` is present in the file.
- Confirm the file is not stale: `find .claude/cache/workflow-state -mmin +1440` should be empty.

**State file left behind after a completed workflow:**

The model is responsible for deleting the state file at the terminal phase (Phase 5 for
workflow-development; Phase 4 for workflow-bug-triage; Step 7 for workflow-pr-review). If
it was skipped, delete manually:
```bash
rm .claude/cache/workflow-state/$(git branch --show-current | tr '/' '-').json
```

**Hook exits non-zero:**

This should never happen — the hook exits 0 unconditionally. If `bash hooks/workflow_resume_hint.sh`
exits non-zero when given a valid payload, check for a syntax error in the script:
`bash -n hooks/workflow_resume_hint.sh`.
