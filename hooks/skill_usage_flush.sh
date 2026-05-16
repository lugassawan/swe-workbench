#!/usr/bin/env bash
# SubagentStop handler — flushes the per-subagent buffer when a dispatched
# subagent finishes.  Emits a single telemetry line via systemMessage so the
# orchestrator's transcript shows which skills the subagent invoked.
#
# Exits 0 unconditionally; emits {} when there is nothing to report.
set -u

input=$(cat)

agent_id=$(printf '%s' "$input" | jq -r '.agent_id // empty')
agent_type=$(printf '%s' "$input" | jq -r '.agent_type // empty')
{ [ -z "$agent_id" ] || [ -z "$agent_type" ]; } && { printf '{}'; exit 0; }

# Sanitize agent_type: plain identifiers only — reject path-traversal attempts.
[[ "$agent_type" =~ ^[A-Za-z0-9_-]+$ ]] || { printf '{}'; exit 0; }

# Scope + opt-out (same gates as the record hook).
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
agent_file="$plugin_root/agents/$agent_type.md"
[ -f "$agent_file" ] || { printf '{}'; exit 0; }
if head -20 "$agent_file" | grep -Eq '^skill_telemetry:[[:space:]]*false[[:space:]]*$'; then
  printf '{}'; exit 0
fi

cache_dir="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/cache/skill-usage"

# Buffer may span today's and yesterday's date-stamped file (straddle midnight).
# Use a glob loop so paths with spaces are handled correctly (compatible with bash 3.2+).
buffers=()
for f in "$cache_dir"/*-"$agent_id".txt; do
  [ -f "$f" ] && buffers+=("$f")
done
[ "${#buffers[@]}" -eq 0 ] && { printf '{}'; exit 0; }

# Dedupe preserving first-seen order; join with ", " in one pass (POSIX awk, no paste/sed).
skills=$(cat "${buffers[@]}" 2>/dev/null | awk '!seen[$0]++ { out = (out ? out ", " : "") $0 } END { print out }')
[ -z "$skills" ] && { printf '{}'; exit 0; }

# Clean up all matching buffers regardless of whether the emit succeeds below.
rm -f "${buffers[@]}" 2>/dev/null || true

# Safely JSON-encode the message.
msg=$(printf 'Skills used by %s: %s' "$agent_type" "$skills" | jq -Rs .)
printf '{"systemMessage": %s, "suppressOutput": true}\n' "$msg"
exit 0
