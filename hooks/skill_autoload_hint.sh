#!/usr/bin/env bash
# PostToolUse:Read|Edit|Write handler — emits a non-blocking hint when the
# touched file's extension maps to a known language-* skill.
#
# Behaviour:
#   • De-duplicates: emits at most once per (session, skill) pair.
#   • Never blocks: exit 0 always.  A broken hook must never gate a tool call.
set -u

# ── extension → skill map ────────────────────────────────────────────────────
ext_to_skill() {
    local ext="$1"
    case "$ext" in
        py)                   echo "language-python" ;;
        ts|tsx|js|jsx|mjs|cjs) echo "language-typescript" ;;
        go)                   echo "language-go" ;;
        rs)                   echo "language-rust" ;;
        java)                 echo "language-java" ;;
        kt|kts)               echo "language-kotlin" ;;
        rb)                   echo "language-ruby" ;;
        swift)                echo "language-swift" ;;
        sh|bash)              echo "language-bash" ;;
        sql)                  echo "language-sql" ;;
        cs)                   echo "language-csharp" ;;
        *)                    echo "" ;;
    esac
}

main() {
    local input file_path session_id ext skill safe_session safe_skill sentinel dir today

    input=$(cat)

    # Extract file path (Read/Edit supply file_path; Write also supplies it)
    file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
    [ -n "$file_path" ] || exit 0

    # Derive extension (lowercase, POSIX tr for Bash 3 compat).
    # Guard: if ext equals the bare filename there was no dot → not an extension.
    ext="${file_path##*.}"
    ext=$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')
    [ "$ext" = "${file_path##*/}" ] && exit 0   # no dot in filename → no extension

    skill=$(ext_to_skill "$ext")
    [ -n "$skill" ] || exit 0             # unmapped extension → no hint

    # Session-scoped de-dup sentinel.
    # Use || true so a jq-absent environment still falls through to the PID fallback.
    session_id=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null) || true
    [ -n "$session_id" ] || session_id="$$"   # fallback: PID (coarse but safe)

    # Sanitize both components: only alphanumeric + dash + underscore
    safe_session="${session_id//[^A-Za-z0-9_-]/_}"
    safe_skill="${skill//[^A-Za-z0-9_-]/_}"

    # Date-scoped subdir provides a coarse TTL: yesterday's sentinels are invisible
    # today, preventing cross-session suppression on long-running machines.
    today=$(date +%Y%m%d 2>/dev/null) || today="default"
    dir="${TMPDIR:-/tmp}/swe_wb_skill_hints/${today}"
    mkdir -p "$dir" 2>/dev/null || exit 0
    sentinel="${dir}/${safe_session}_${safe_skill}"

    # Already hinted this session for this skill → silent no-op
    [ -f "$sentinel" ] && exit 0
    touch "$sentinel" 2>/dev/null || true

    # Emit hint via hookSpecificOutput
    local hint="Consider \`swe-workbench:${skill}\` for .${ext} work — invoke it via the Skill tool to apply language-specific idioms."
    jq -cn --arg ctx "$hint" \
        '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}' \
        2>/dev/null || true
}

main
exit 0
