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
    local wt_real="$1" project f conf="${CLAUDE_CONFIG_DIR:-${HOME:-/nonexistent}/.claude}"
    project=$(
        cd "$wt_real" 2>/dev/null || exit 0
        common=$(git rev-parse --git-common-dir 2>/dev/null) || exit 0
        cd "$common" 2>/dev/null && cd .. && pwd -P
    ) || project=""
    for f in \
        "$conf/settings.json" \
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

# True when a segment of $1 launches `rtk [proxy] git`; $2 is what the user typed. If $2 has
# no `rtk git` of its own, any `rtk git` is RTK's splice and WRAPPED=1 bars a rendered fix.
launches_rtk_git() {
    local effective="$1" typed="$2" seg word wrapped skip segments line
    local re_cmd='^([^[:space:]]*/)?rtk[[:space:]]+(proxy[[:space:]]+)?([^[:space:]]*/)?git([[:space:]]|$)'
    local re_any='(^|[[:space:]])rtk[[:space:]]+(proxy[[:space:]]+)?git([[:space:]]|$)'
    local typed_has_rtk_git=0
    while IFS= read -r line; do
        [[ $line =~ $re_any ]] && typed_has_rtk_git=1
    done <<EOF
$(split_segments "$typed")
EOF
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
                -* | [0-9]*) # wrapper options and `timeout 5`
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
        if [ "$typed_has_rtk_git" -eq 0 ] && [[ $line =~ $re_any ]]; then
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

# The typed command with `RTK_DISABLED=1` spliced in at each git command position (a typed
# `[path/]rtk [proxy] git` becomes plain `git`). Quotes, comments and continuations are honoured.
render_fix() {
    printf '%s\n' "$1" | awk '
        BEGIN { sq = "\047"; dq = "\""; q = ""; start = 1 }
        {
            line = $0; n = length(line); out = ""; cont = 0
            i = 1
            while (i <= n) {
                c = substr(line, i, 1)
                if (q == sq) { out = out c; if (c == sq) q = ""; i++; continue }
                if (q == dq) {
                    if (c == "\\") { out = out c substr(line, i + 1, 1); i += 2; continue }
                    out = out c
                    if (c == dq) q = ""
                    i++; continue
                }
                if (c == "\\") {
                    if (i == n) cont = 1
                    out = out c substr(line, i + 1, 1); i += 2; start = 0; continue
                }
                if (c == "#" && (i == 1 || substr(line, i - 1, 1) ~ /[ \t;&|()]/)) {
                    out = out substr(line, i); i = n + 1; continue
                }
                if (c == sq || c == dq) { q = c; out = out c; start = 0; i++; continue }
                if (c == ";" || c == "&" || c == "|" || c == "(") { out = out c; start = 1; i++; continue }
                if (start && (c == " " || c == "\t")) { out = out c; i++; continue }
                if (start) {
                    rest = substr(line, i)
                    if (match(rest, /^([A-Za-z_][A-Za-z0-9_]*=[^ \t]*[ \t]+)*(([^ \t]*\/)?rtk[ \t]+(proxy[ \t]+)?)?git([ \t]|$)/)) {
                        mlen = RLENGTH
                        m = substr(rest, 1, mlen)
                        assigns = ""
                        if (match(m, /^([A-Za-z_][A-Za-z0-9_]*=[^ \t]*[ \t]+)*/)) assigns = substr(m, 1, RLENGTH)
                        tail = substr(m, length(assigns) + 1)
                        sub(/^(([^ \t]*\/)?rtk[ \t]+(proxy[ \t]+)?)?git/, "", tail)
                        out = out "RTK_DISABLED=1 " assigns "git" tail
                        i += mlen
                        start = 0
                        continue
                    }
                }
                out = out c; start = 0; i++
            }
            print out
            if (q == "" && !cont) start = 1
        }'
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

# A private, owned, non-symlink marker dir; anything else fails the hook open.
marker_dir_trusted() {
    [ ! -L "$MARKER_DIR" ] && [ -d "$MARKER_DIR" ] && [ -O "$MARKER_DIR" ]
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
    [ -d "$MARKER_DIR" ] || mkdir -m 700 "$MARKER_DIR" 2>/dev/null
    marker_dir_trusted || return 0
    prune_stale_markers
    [ -f "$MARKER" ] && prev=$(<"$MARKER")
    tmp=$(mktemp "$MARKER_DIR/.tmp.XXXXXX" 2>/dev/null) || return 0
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
    local input="$1" session_marker="$2" wt_real cwd_real cmd class fix head
    marker_dir_trusted || return 0
    # a subagent without its own marker inherits the session's isolation
    [ -f "$MARKER" ] || MARKER="$session_marker"
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
    # shellcheck disable=SC2016 # `$(` and backtick are literal patterns here
    case "$cmd" in
        *'$('* | *\`* | *'<<'*) class="parse-complexity" ;;
    esac
    [ "$class" != "containment" ] || [ "$WRAPPED" -eq 0 ] || class="no-exact-fix"
    if [ "$class" = "containment" ]; then
        # an undecidable re-check counts the same as one that would be denied again
        fix=$(render_fix "$cmd")
        if ! effective_command "$fix" || launches_rtk_git "$EFFECTIVE" "$fix"; then
            class="no-exact-fix"
        fi
    fi

    head="BLOCKED [rtk-worktree:${class}]: this session is isolated in ${wt_real}; RTK's hook rewrites this to \`rtk git …\`, which Claude Code's worktree guard refuses."
    case "$class" in
        containment)
            printf '%s Next step — run exactly:\n' "$head" >&2
            printf '%s\n' "$fix" | sed 's/^/  /' >&2
            ;;
        parse-complexity)
            # shellcheck disable=SC2016 # backticks are literal message text
            printf '%s This command uses a substitution or heredoc, which cannot be rewritten safely. Next step — run each git command as its own Bash call, prefixed with `RTK_DISABLED=1 `, e.g. `RTK_DISABLED=1 git status`.\n' "$head" >&2
            ;;
        *)
            # shellcheck disable=SC2016 # backticks are literal message text
            printf '%s No exact fix could be verified for this command (a launcher wrapper such as `time`, or a form RTK still rewrites). Next step — run each git command as its own Bash call, prefixed with `RTK_DISABLED=1 ` and without wrappers, e.g. `RTK_DISABLED=1 git status`.\n' "$head" >&2
            ;;
    esac
    exit 2
}

main() {
    local input meta event tool session agent
    [ "${SWE_WORKBENCH_RTK_WORKTREE_GUARD:-1}" != "0" ] || return 0
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
    local session_marker="$MARKER"
    [ -z "$agent" ] || MARKER="${MARKER}_${agent//[^A-Za-z0-9_-]/_}"

    case "$event:$tool" in
        PostToolUse:EnterWorktree) on_enter ;;
        PostToolUse:ExitWorktree) on_exit ;;
        PreToolUse:Bash) on_bash "$input" "$session_marker" ;;
    esac
    return 0
}

main
exit 0
