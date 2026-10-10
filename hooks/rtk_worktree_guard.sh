#!/usr/bin/env bash
# Denies `rtk [proxy] git ...` inside an EnterWorktree-isolated session and names the
# RTK_DISABLED=1 form; usability only, fail-open, Claude Code only (docs/cross-harness.md §1).
set -u

MARKER_DIR="${TMPDIR:-/tmp}/swe_wb_rtk_worktree"
REWRITE_TICKS=60 # x ~0.03s per poll is ~2s wall; macOS has no `timeout`

RW_PID=""
RW_TMP=""
EFFECTIVE=""
WRAPPED=0
CWD=""
WT=""
MARKER=""

# shellcheck disable=SC2329 # invoked via the EXIT trap
cleanup() {
    if [ -n "$RW_PID" ]; then
        kill "$RW_PID" 2>/dev/null
        wait "$RW_PID" 2>/dev/null
    fi
    [ -n "$RW_TMP" ] && rm -f "$RW_TMP"
    return 0
}
trap cleanup EXIT

physdir() {
    (CDPATH='' cd "$1" 2>/dev/null && pwd -P)
}

# True when a hook `command` under .hooks of settings file $1 runs `rtk hook claude`.
settings_has_rtk_hook() {
    [ -f "$1" ] || return 1
    jq -e '[.hooks // {} | .. | objects | .command? | strings
            | select(test("(^|[/\\s])rtk hook claude"))] | length > 0' "$1" >/dev/null 2>&1
}

rtk_hook_configured() {
    local wt_real="$1" project f
    project=$(
        cd "$wt_real" 2>/dev/null || exit 0
        common=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
        cd "$common" 2>/dev/null && cd .. && pwd -P
    ) || project=""
    for f in \
        "${HOME:-/nonexistent}/.claude/settings.json" \
        "$wt_real/.claude/settings.json" \
        "$wt_real/.claude/settings.local.json" \
        "${project:-/nonexistent}/.claude/settings.json" \
        "${project:-/nonexistent}/.claude/settings.local.json"; do
        settings_has_rtk_hook "$f" && return 0
    done
    return 1
}

# One command segment per line. Quoted text collapses to Q, comments and heredoc bodies
# are dropped, and `\`-newline joins lines, so only executable words remain.
split_segments() {
    printf '%s\n' "$1" | awk '
        BEGIN { sq = "\047"; dq = "\""; q = ""; hd = "" }
        {
            line = $0
            if (hd != "") {
                t = line; sub(/^\t+/, "", t)
                if (t == hd) hd = ""
                next
            }
            n = length(line); out = ""; cont = 0
            for (i = 1; i <= n; i++) {
                c = substr(line, i, 1)
                if (q == sq) { if (c == sq) q = ""; continue }
                if (q == dq) {
                    if (c == "\\") { i++; continue }
                    if (c == dq) q = ""
                    continue
                }
                if (c == "\\") { if (i == n) cont = 1; i++; continue }
                if (c == "#" && (i == 1 || substr(line, i - 1, 1) ~ /[ \t;&|()]/)) break
                if (c == sq || c == dq) { q = c; out = out "Q"; continue }
                if (c == "<" && substr(line, i + 1, 1) == "<" && substr(line, i + 2, 1) != "<" &&
                    (i == 1 || substr(line, i - 1, 1) != "<") &&
                    substr(line, 1, i - 1) !~ /\(\([^)]*$/) {
                    rest = substr(line, i + 2)
                    if (match(rest, /^-?[ \t]*[^ \t;&|()<>]+/)) {
                        w = substr(rest, RSTART, RLENGTH)
                        sub(/^-?[ \t]*/, "", w)
                        gsub("[\\\\\"\047]", "", w)
                        hd = w
                    }
                    i++
                    continue
                }
                if (c == ";" || c == "&" || c == "|" || c == "(" || c == ")" || c == "`") {
                    out = out "\n"; continue
                }
                out = out c
            }
            if (q == "" && !cont) out = out "\n"
            printf "%s", out
        }'
}

# True when a segment of $1 launches `rtk [proxy] git`; $2 is what the user typed. With no
# typed `rtk`, any `rtk git` is RTK's splice; WRAPPED=1 then bars a rendered fix.
launches_rtk_git() {
    local effective="$1" typed="$2" seg word wrapped skip segments
    local re_cmd='^([^[:space:]]*/)?rtk[[:space:]]+(proxy[[:space:]]+)?([^[:space:]]*/)?git([[:space:]]|$)'
    local re_any='(^|[[:space:]])rtk[[:space:]]+(proxy[[:space:]]+)?git([[:space:]]|$)'
    local line
    WRAPPED=0
    segments=$(split_segments "$effective")
    while IFS= read -r line; do
        seg="$line"
        wrapped=0
        skip=0
        while :; do
            seg="${seg#"${seg%%[![:space:]]*}"}"
            word="${seg%%[[:space:]]*}"
            [ -n "$word" ] || break
            if [ "$skip" -eq 1 ]; then # value of `nice -n N`, `timeout -k N`
                skip=0
                seg="${seg#"$word"}"
                continue
            fi
            case "$word" in
                [A-Za-z_]*=* | env) seg="${seg#"$word"}" ;;
                time | command | builtin | exec | nohup | nice | timeout)
                    wrapped=1
                    seg="${seg#"$word"}"
                    ;;
                -n | -k | -s)
                    [ "$wrapped" -eq 1 ] || break
                    skip=1
                    seg="${seg#"$word"}"
                    ;;
                -*)
                    [ "$wrapped" -eq 1 ] || break
                    seg="${seg#"$word"}"
                    ;;
                *) break ;;
            esac
        done
        if [[ $seg =~ $re_cmd ]]; then
            WRAPPED=$wrapped
            return 0
        fi
        if [[ $typed != *rtk* && $line =~ $re_any ]]; then
            WRAPPED=1
            return 0
        fi
    done <<EOF
$segments
EOF
    return 1
}

# Sets EFFECTIVE to what will actually run. rc 0 or 3 carry the rewritten command on
# stdout (0 when an allow rule covers it); rc 1 means unchanged; anything else is undecidable.
effective_command() {
    local cmd="$1" ticks=0 rc out
    EFFECTIVE=""
    RW_TMP=$(mktemp "${TMPDIR:-/tmp}/swe_wb_rtk_rewrite.XXXXXX" 2>/dev/null) || {
        RW_TMP=""
        return 1
    }
    rtk rewrite -- "$cmd" >"$RW_TMP" 2>/dev/null </dev/null &
    RW_PID=$!
    while kill -0 "$RW_PID" 2>/dev/null; do
        ticks=$((ticks + 1))
        if [ "$ticks" -gt "$REWRITE_TICKS" ]; then
            kill "$RW_PID" 2>/dev/null
            wait "$RW_PID" 2>/dev/null
            RW_PID=""
            rm -f "$RW_TMP"
            RW_TMP=""
            return 1
        fi
        sleep 0.02
    done
    wait "$RW_PID"
    rc=$?
    RW_PID=""
    out=$(<"$RW_TMP")
    rm -f "$RW_TMP"
    RW_TMP=""
    case "$rc:${out:+text}" in
        0:text | 3:text) EFFECTIVE="$out" ;;
        0: | 1:*) EFFECTIVE="$cmd" ;;
        *) return 1 ;;
    esac
    return 0
}

# Replace each `[path/]rtk [proxy] [path/]git` with `RTK_DISABLED=1 git`.
render_fix() {
    printf '%s\n' "$1" | sed -E \
        's/(^|[[:space:];&|(])([^[:space:]]*\/)?rtk[[:space:]]+(proxy[[:space:]]+)?([^[:space:]]*\/)?git([[:space:]]|$)/\1RTK_DISABLED=1 git\5/g'
}

# Drop markers whose worktree is gone (headless runs end without ExitWorktree).
# Empty files are left alone: another session may be mid-write.
prune_stale_markers() {
    local f recorded
    for f in "$MARKER_DIR"/*; do
        [ -f "$f" ] || continue
        recorded=$(<"$f")
        [ -n "$recorded" ] || continue
        [ -d "$recorded" ] || rm -f "$f" 2>/dev/null
    done
    return 0
}

on_enter() {
    local wt_real prev="" tmp
    [ -n "$WT" ] || return 0
    wt_real=$(physdir "$WT") || return 0
    [ -n "$wt_real" ] || return 0
    rtk_hook_configured "$wt_real" || return 0
    command -v rtk >/dev/null 2>&1 || return 0
    # only when RTK would actually rewrite git here (not e.g. exclude_commands = ["git"])
    effective_command "git status" && launches_rtk_git "$EFFECTIVE" "git status" || return 0
    mkdir -p "$MARKER_DIR" 2>/dev/null || return 0
    prune_stale_markers
    [ -f "$MARKER" ] && prev=$(<"$MARKER")
    tmp="$MARKER.$$"
    if ! { printf '%s\n' "$wt_real" >"$tmp" && mv -f "$tmp" "$MARKER"; } 2>/dev/null; then
        rm -f "$tmp" 2>/dev/null
        return 0
    fi
    [ "$prev" = "$wt_real" ] && return 0
    jq -cn --arg ctx "RTK rewrites git here into a form Claude Code's worktree guard refuses; prefix every git segment with \`RTK_DISABLED=1 \`." \
        '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}' 2>/dev/null
    return 0
}

on_exit() {
    rm -f "$MARKER" 2>/dev/null
    rmdir "$MARKER_DIR" 2>/dev/null
    return 0
}

on_bash() {
    local input="$1" wt_real cwd_real cmd class fix head
    [ -f "$MARKER" ] || return 0
    wt_real=$(<"$MARKER")
    [ -n "$wt_real" ] && [ -n "$CWD" ] || return 0
    cwd_real=$(physdir "$CWD") || return 0
    case "$cwd_real/" in
        "$wt_real"/*) ;;
        *) return 0 ;;
    esac
    command -v rtk >/dev/null 2>&1 || return 0
    cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null) || return 0
    [ -n "$cmd" ] || return 0

    effective_command "$cmd" || return 0
    launches_rtk_git "$EFFECTIVE" "$cmd" || return 0

    class="containment"
    [ "$WRAPPED" -eq 0 ] || class="parse-complexity"
    # shellcheck disable=SC2016 # `$(` and backtick are literal patterns here
    case "$cmd" in
        *\'* | *\"* | *'$('* | *\`* | *'<<'*) class="parse-complexity" ;;
    esac
    if [ "$class" = "containment" ]; then
        # an undecidable re-check counts the same as one that would be denied again
        fix=$(render_fix "$EFFECTIVE")
        if ! effective_command "$fix" || launches_rtk_git "$EFFECTIVE" "$fix"; then
            class="parse-complexity"
        fi
    fi

    head="BLOCKED [rtk-worktree:${class}]: this session is isolated in ${wt_real}; RTK's hook rewrites this to \`rtk git …\`, which Claude Code's worktree guard refuses."
    if [ "$class" = "containment" ]; then
        printf '%s Next step — run exactly:\n' "$head" >&2
        printf '%s\n' "$fix" | sed 's/^/  /' >&2
    else
        # shellcheck disable=SC2016 # backticks are literal message text
        printf '%s This command is too complex to rewrite safely. Next step — run each git command as its own Bash call, prefixed with `RTK_DISABLED=1 ` and without launcher wrappers such as `time` or `command`, e.g. `RTK_DISABLED=1 git status`.\n' "$head" >&2
    fi
    exit 2
}

main() {
    local input meta event tool session agent
    command -v jq >/dev/null 2>&1 || return 0
    input=$(cat) || return 0
    meta=$(printf '%s' "$input" | jq -r '[.hook_event_name // "", .tool_name // "", .session_id // "",
        .agent_id // "", .cwd // "", (.tool_response.worktreePath? // "")] | map(tostring) | join("\u001f")' 2>/dev/null) || return 0
    IFS=$'\037' read -r event tool session agent CWD WT <<EOF
$meta
EOF
    session="${session//[^A-Za-z0-9_-]/_}"
    [ -n "$session" ] || return 0
    MARKER="$MARKER_DIR/$session"
    [ -z "$agent" ] || MARKER="${MARKER}_${agent//[^A-Za-z0-9_-]/_}"

    case "$event:$tool" in
        PostToolUse:EnterWorktree) on_enter ;;
        PostToolUse:ExitWorktree) on_exit ;;
        PreToolUse:Bash) on_bash "$input" ;;
    esac
    return 0
}

main
exit 0
