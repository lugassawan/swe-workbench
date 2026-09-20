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

# Sanitize agent_id and agent_type: plain identifiers only — reject path-traversal attempts.
[[ "$agent_id" =~ ^[A-Za-z0-9_-]+$ ]] || { printf '{}'; exit 0; }
[[ "$agent_type" =~ ^[A-Za-z0-9_-]+$ ]] || { printf '{}'; exit 0; }

cache_dir="${CLAUDE_PROJECT_DIR:-$PWD}/.claude/cache/skill-usage"

# --- Preload citation harvest -----------------------------------------------
# Independent of the skill-usage-buffer flush below, and NOT gated on the
# skill_telemetry opt-out check further down: SWB-CANARIES-APPLIED citations
# are a distinct signal (which preloaded skills actually shaped the
# subagent's response) from the Skill-tool usage buffer that opt-out exists
# for, so a telemetry-opted-out agent still gets its citations harvested.
# Not gated on skill_telemetry:false — that flag silences the ephemeral,
# transcript-visible Skill-tool usage message; citation harvest is a
# separate, persistent measurement C2 needs collected across all agents
# regardless.
last_msg=$(printf '%s' "$input" | jq -r '.last_assistant_message // empty')
if [ -n "$last_msg" ]; then
  # An optional leading backtick is tolerated: the instruction fragment shows the
  # marker as inline code, so a model can plausibly reproduce its own closing line
  # the same way. Backticks are never valid inside a skill id, so deleting every
  # backtick from the captured line before parsing is lossless and also survives
  # per-id backticking.
  citation_line=$(printf '%s\n' "$last_msg" | grep -E '^`?SWB-CANARIES-APPLIED:' | tail -n1)
  if [ -n "$citation_line" ]; then
    captured=$(printf '%s\n' "$citation_line" | tr -d '`' \
      | sed -E 's/^SWB-CANARIES-APPLIED:[[:space:]]*//')
    cited_json=$(jq -n --arg raw "$captured" '
      ($raw | gsub("^\\s+|\\s+$"; "")) as $trimmed
      | if ($trimmed == "NONE" or $trimmed == "") then []
        else ($trimmed | split(",") | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0)))
        end
    ' 2>/dev/null)
  else
    # No marker line anywhere in the response. Still record the dispatch, with a
    # null cited_skills, so the reporter's denominator is every observed dispatch
    # rather than only the ones that complied with the trailing instruction —
    # a dropped marker is itself the signal that matters most here. null (marker
    # absent) stays distinct from [] (agent explicitly emitted NONE).
    cited_json=null
  fi
  if [ -n "$cited_json" ]; then
    citation_record=$(jq -nc \
      --arg agent_type "$agent_type" \
      --arg agent_id "$agent_id" \
      --argjson cited_skills "$cited_json" \
      '{agent_type: $agent_type, cited_skills: $cited_skills, agent_id: $agent_id}' 2>/dev/null)
    if [ -n "$citation_record" ]; then
      mkdir -p "$cache_dir" 2>/dev/null
      printf '%s\n' "$citation_record" >>"$cache_dir/canary-citations.jsonl" 2>/dev/null || true
    fi
  fi
fi
# --- end preload citation harvest -------------------------------------------

# Scope + opt-out (same gates as the record hook).
plugin_root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
agent_file="$plugin_root/agents/$agent_type.md"
[ -f "$agent_file" ] || { printf '{}'; exit 0; }
if head -20 "$agent_file" | grep -Eq '^skill_telemetry:[[:space:]]*false[[:space:]]*$'; then
  printf '{}'; exit 0
fi

# Buffer may span today's and yesterday's date-stamped file (straddle midnight).
# The 8-digit bracket prefix is intentional: without it, "*-foo.txt" greedily
# matches a sibling agent "bar-foo"'s "<date>-bar-foo.txt" (id allows hyphens).
# The suffix -"$agent_id".txt is an exact match, so a longer id ("bar-foo") never
# matches a shorter one's glob ("foo") either. Compatible with bash 3.2+ (POSIX
# bracket classes, no extglob required).
buffers=()
for f in "$cache_dir"/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-"$agent_id".txt; do
  [ -f "$f" ] && buffers+=("$f")
done
[ "${#buffers[@]}" -eq 0 ] && { printf '{}'; exit 0; }

# Dedupe preserving first-seen order; join with ", " in one pass (POSIX awk, no paste/sed).
skills=$(cat "${buffers[@]}" 2>/dev/null | awk '!seen[$0]++ { out = (out ? out ", " : "") $0 } END { print out }')
[ -z "$skills" ] && { printf '{}'; exit 0; }

# Safely JSON-encode the message. On encode failure emit a clean {} and leave the
# buffers in place so a later flush can retry — never emit malformed JSON.
msg=$(printf 'Skills used by %s: %s' "$agent_type" "$skills" | jq -Rs .) || { printf '{}\n'; exit 0; }
printf '{"systemMessage": %s, "suppressOutput": true}\n' "$msg"

# Clean up the buffers only after a successful emit.
rm -f "${buffers[@]}" 2>/dev/null || true
exit 0
