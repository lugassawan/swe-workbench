#!/usr/bin/env bash
# PreToolUse:Skill handler — records skill name into a per-subagent buffer
# when the call originates inside a dispatched subagent.
#
# Never blocks: exit 2 from a PreToolUse hook would deny the Skill call,
# which is unacceptable for an observation-only hook. Exit 0 always.
set -u

input=$(cat)

agent_id=$(printf '%s' "$input" | jq -r '.agent_id // empty')
[ -z "$agent_id" ] && exit 0          # top-level orchestrator → no-op

# Sanitize agent_id: plain identifiers only — same rule as agent_type.
[[ "$agent_id" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0

agent_type=$(printf '%s' "$input" | jq -r '.agent_type // empty')
skill=$(printf '%s' "$input" | jq -r '.tool_input.skill // empty')
[ -z "$skill" ] && exit 0             # malformed input → no-op

# Sanitize skill: reject values that jq -r would expand to newlines or shell metas.
[[ "$skill" =~ ^[A-Za-z0-9_:/-]+$ ]] || exit 0

# Sanitize agent_type: plain identifiers only — reject path-traversal attempts.
[[ "$agent_type" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0

# Scope: only track agents owned by this plugin.
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
agent_file="$plugin_root/agents/$agent_type.md"
[ -f "$agent_file" ] || exit 0

# Opt-out: frontmatter `skill_telemetry: false` in the first 20 lines.
if head -20 "$agent_file" | grep -Eq '^skill_telemetry:[[:space:]]*false[[:space:]]*$'; then
  exit 0
fi

cache_dir="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/cache/skill-usage"
mkdir -p "$cache_dir" 2>/dev/null || exit 0
buffer="$cache_dir/$(date +%Y%m%d)-$agent_id.txt"

# Append skill name. Dedup happens at flush time so this path stays fast.
printf '%s\n' "$skill" >>"$buffer" 2>>"$cache_dir/.errors.log" || true

# Opportunistic sweep: drop buffers older than 24h. Throttled to ~1 in 50 calls
# so this maintenance traversal doesn't ride every Skill dispatch on the telemetry
# hot path (#501); orphans are still reaped within ~50 calls. SKILL_SWEEP_EVERY is
# a test seam: 1 forces every call, 0 disables it deterministically (a large
# divisor only makes firing improbable — RANDOM can still draw exactly 0).
sweep_every="${SKILL_SWEEP_EVERY:-50}"
if (( sweep_every > 0 )) && (( RANDOM % sweep_every == 0 )); then
  find "$cache_dir" -maxdepth 1 \( -name '*-*.txt' -o -name '.errors.log' \) -mmin +1440 -delete 2>/dev/null || true
fi

exit 0
