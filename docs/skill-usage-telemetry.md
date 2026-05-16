# Skill-usage telemetry

When the orchestrator dispatches a subagent via the `Agent` tool, any skills that subagent invokes are invisible to the orchestrator — it only receives the subagent's final text output.  The telemetry hooks surface those invocations by printing a single informational line into the orchestrator's transcript after each subagent finishes:

```
Skills used by <agent-type>: <skill-1>, <skill-2>, ...
```

## How it works

Two hooks cooperate:

| Hook | Script | Event |
|---|---|---|
| `PreToolUse:Skill` | `hooks/skill_usage_record.sh` | Fires on every `Skill` tool call.  When inside a subagent (`agent_id` present in stdin), appends the skill name to a date-stamped buffer: `.claude/cache/skill-usage/YYYYMMDD-<agent_id>.txt`. |
| `SubagentStop` | `hooks/skill_usage_flush.sh` | Fires when a subagent finishes.  Reads the buffer, deduplicates (preserving first-seen order), formats the line, emits it via `systemMessage`, then deletes the buffer. |

Top-level orchestrator skill calls produce **no line**. Zero-skill subagent runs produce **no line**.  The feature is information-only — it never blocks or modifies tool calls.

## Where buffers live

```
<project-root>/.claude/cache/skill-usage/
  20260517-abc-123.txt      ← one file per in-flight subagent
  .errors.log               ← hook errors (only present when something went wrong)
```

Buffers older than 24 hours are swept opportunistically on each `PreToolUse:Skill` call.  `SubagentStop` deletes the buffer immediately after flushing.  Under normal operation the directory stays empty between agent runs.

## Opting out

An agent can suppress telemetry for itself by adding `skill_telemetry: false` to its YAML frontmatter (within the first 20 lines of the file):

```markdown
---
name: my-agent
skill_telemetry: false
model: sonnet
---
```

Both hooks check this flag independently, so a crash between `PreToolUse` and `SubagentStop` cannot cause a buffer to accumulate for an opted-out agent.

## Scope

The hooks only track agents whose `.md` file lives under `<plugin-root>/agents/`.  Other plugins ship their own equivalent hooks if they want telemetry for their subagents.

## Troubleshooting

If you expect a "Skills used by …" line but don't see one:

1. Check `.claude/cache/skill-usage/.errors.log` for hook errors.
2. Confirm the subagent's `.md` file exists under `agents/` and does **not** have `skill_telemetry: false`.
3. Confirm `CLAUDE_PLUGIN_ROOT` resolves to the plugin root (hooks use this to locate agent files).

## Security note

Skill names land in the `systemMessage` field visible in the orchestrator's transcript.  If a future plugin author ever encodes sensitive data into skill names, those names would appear in the transcript.  Skill names in this plugin are all short, non-sensitive identifiers (e.g. `swe-workbench:principle-code-review`).
