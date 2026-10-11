#!/usr/bin/env bash
# PreToolUse:Bash guard — block destructive commands and short-circuit safe ones.
#
# Blocks:
#   - rm -rf against /, /*, ~, $HOME, /Users[/<user>], /home[/<user>]
#   - git push --force / -f to main/master/release/*
#   - git reset --hard on main/master/release/*
#   - a `pi` invocation carrying -p/--print in the same command segment (nested
#     non-interactive pi session — the bash escape hatch around the subagent
#     dispatcher's --exclude-tools recursion guard; see
#     docs/task-dispatch.md)
#
# Short-circuits (exit 0, no greps) for commands that contain none of "rm",
# "git", or "pi". This is the common case (ls, cat, echo, make, npm, …) and
# removes the per-call grep tax flagged in #233.
#
# Out of scope: ${HOME} brace-form; ANSI-C $'...' quoting; path normalization via .. traversal; compound cd (cwd not in hook payload);
# IFS/word-splitting substitution (e.g. rm${IFS}-rf, pi${IFS}-p) — a shared limitation of the
# regex/tr token-matching approach across all three detectors (rm, git, pi), not specific to any one.
# A backslash-escaped quote (e.g. `\"`) inside an already-open double-quoted string desyncs the
# comment-stripper's quote tracker (pre-existing, predates the pi work, shared by rm/git too) — a
# `#` that's really inside the string can get treated as a real comment. Indirection that supplies
# either the `pi` token or the `-p`/`--print` flag from somewhere other than literal argv text
# (command substitution — `$(which pi) -p x`; parameter expansion — `$P -p x`; another program's
# output — `echo -p x | xargs pi`) defeats segment-scoping, since the guard only ever sees the
# unresolved source text — inherent to a text-scanning guard rather than a gap specific to this
# detector. The `pi` detector matches its command-name token case-insensitively (a case-insensitive
# filesystem, e.g. macOS's default, resolves "Pi"/"PI" to the same binary); `rm`/`git` do not get the
# same treatment here — a pre-existing gap, not introduced or widened by this change.
# --force-with-lease/--force-if-includes intentionally unblocked (#163); quote-stripping may
# over-block a force-push within its command segment (accepted fail-safe); a remote literally
# named main/master over-blocks. The push-token scan trusts a small allowlist of known
# BOOLEAN-only push flags and defensively consumes the next token for any other `-*` flag
# (assumes it takes a separate-word value, e.g. `-o ci.skip`) so an unknown flag's value can never
# be miscounted as the remote/refspec (#501 senior-engineer consult); an unrecognized flag that
# actually takes NO value will over-block by one token (fail-safe direction, not a bypass).
# Quotes are stripped before matching (same fail-safe direction as the force-push over-block
# above), so a `pi -p` mention inside an unrelated quoted string (e.g. a commit message) can
# over-block too — accepted, not special-cased.

set -u

if ! cmd=$(jq -r '.tool_input.command // ""'); then
  echo 'bash_guard: jq parse error — blocking by default' >&2
  exit 2
fi

# Strip shell comments per-line BEFORE folding newlines or joining backslash
# continuations. A `#` comment ends at its line's newline; folding first would
# let an early comment swallow a destructive command on a later line (e.g.
# "echo hi # note\nrm -rf ~"). A trailing backslash INSIDE a comment has no
# continuation meaning in real bash either — the comment still ends at the
# physical newline — so comment-stripping must run BEFORE the backslash-join
# below, not after: joining first would glue a live command on the next line
# onto the end of a "# note \"-style comment, and the comment-stripper would
# then discard it as if it were part of the same comment.
# Quote-aware: a `#` inside a single- or double-quoted string (e.g. a commit
# message referencing an issue number, `-m "fix #501"`) is NOT a real shell
# comment and must not truncate real command text after it (#501 review).
# Quote state is tracked in a BEGIN block (not reset per-line) so it persists
# across an embedded newline inside a still-open quote — e.g. a multi-line -m
# commit message — otherwise a '#'-starting continuation line would swallow
# real command text that follows the closing quote on the SAME line (#501
# re-review finding).
_nc=$(printf '%s' "$cmd" | awk '
BEGIN { in_sq = 0; in_dq = 0 }
{
  line = $0; out = ""; n = length(line)
  for (i = 1; i <= n; i++) {
    c = substr(line, i, 1)
    if (c == "\x27" && !in_dq) { in_sq = !in_sq; out = out c; continue }
    if (c == "\"" && !in_sq)  { in_dq = !in_dq; out = out c; continue }
    if (c == "#" && !in_sq && !in_dq && (i == 1 || substr(line, i-1, 1) ~ /[ \t]/)) break
    out = out c
  }
  print out
}')

# Join backslash-continued lines AFTER comment-stripping (see above), still
# BEFORE quote tracking and fast-gate normalization. Real bash removes a
# trailing backslash-newline entirely — zero characters inserted — so a
# continuation splitting mid-token (e.g. `r\`⏎`m -rf /`, `p\`⏎`i -p x`)
# resolves to one contiguous word there too. Folding the newline to a SPACE (as
# the fast-gate normalization below does for genuine multi-line commands)
# would leave the token split and let it evade every detector's token match by
# hiding in the seam; joining here, once, benefits the fast gate and all
# detectors alike. Parity-aware: real bash only continues on an ODD trailing-
# backslash count (an unpaired `\` right before the newline) — an EVEN count is
# N/2 literal escaped-backslash pairs with no continuation at all. Stripping
# exactly one trailing backslash unconditionally (as an earlier version of this
# stage did) mis-treats an even count as a continuation too, joining two
# genuinely separate commands with zero characters between them and erasing
# the word boundary once the leftover backslash is later deleted by the
# `tr -d` below — hiding whatever destructive command started the second line
# from every detector.
_bj=$(printf '%s' "$_nc" | awk '
{
  line = $0; ll = length(line); nb = 0
  while (nb < ll && substr(line, ll - nb, 1) == "\\") nb++
  if (nb % 2 == 1) printf "%s", substr(line, 1, ll - 1); else print line
}')

# Normalise separators AND newlines/tabs/backticks to spaces so rm/git after
# ; | & \n \t \` are still detected — the fast-gate `case` and the grep
# detectors must share ONE separator alphabet (gate saw ';|&', grep saw
# [[:space:]]).
# shellcheck disable=SC2016  # backtick in tr's SET1 is a literal char, not command substitution
_norm=$(printf '%s' "$_bj" | tr ';|&\n\t`' '      ')

# Fully normalise BEFORE the fast gate, not after: turning "(" and ")" into SPACES (not
# deleting them) handles $(...), <(...), >(...), and bare (...) uniformly, since whatever
# preceded "(" no longer occupies the whitespace-or-start position the anchor regex requires.
# Deleting quotes/brackets/backslashes closes quote-wrapped/backslash-escaped rm ("rm", 'rm',
# \rm). Gate and detector now both run on this SAME normalized text ($norm), closing the same
# class of gate/detector divergence for quote-wrapped rm.
norm=$(printf '%s' "$_norm" | tr '()' '  ' | tr -d "'\"[]{}\\\\")

# The "pi" token in the gate is matched with an explicit case-insensitive character class
# ([Pp][Ii]), not `shopt -s nocasematch` — that shopt would apply to the WHOLE case
# statement, loosening rm/git's matching too (out of scope here). "Pi"/"PI" resolve to the
# exact same binary as "pi" on a case-insensitive filesystem (macOS's default) — a plausible
# typo given the product is styled "Pi" with a capital P elsewhere in this repo's own docs,
# not just a deliberate evasion. Flags stay case-sensitive (real CLI parsers don't accept
# "--PRINT" as "--print"), so only the command-name token gets this treatment.
case "$norm" in
  rm\ *|*\ rm\ *|*git*|[Pp][Ii]\ *|*\ [Pp][Ii]\ *|*/[Pp][Ii]\ *) ;;
  *)                                                             exit 0 ;;
esac

# shellcheck disable=SC2016  # $HOME in single quotes is intentional: matches literal text, not the shell variable
# [rR] covers both -rf and -Rf (BSD/macOS rm accepts -R as synonym for -r).
if echo "$norm" | grep -Eq \
   '(^|[[:space:]])rm[[:space:]]+-[a-zA-Z]*[rR][a-zA-Z]*[fF]?[[:space:]]+(/(\*|[[:space:]]|$)|(~|\$HOME)(/[^[:space:]]*)?([[:space:]]|$)|(/Users|/home)(/[^/[:space:]]+)?([[:space:]]|/|$))'; then
  echo 'BLOCKED: destructive rm against root or home' >&2
  exit 2
fi

# Shared quote- and escape-aware shell segmenter. `tab_mode` preserves literal
# tabs for push matching and folds them for the pi detector.
# shellcheck disable=SC2016 # AWK source is intentionally a single-quoted literal.
_segment_awk='
  BEGIN { in_sq = 0; in_dq = 0 }
  {
    line = $0; n = length(line); out = ""
    for (i = 1; i <= n; i++) {
      c = substr(line, i, 1)
      if (c == "\\" && !in_sq) { i++; if (i <= n) out = out substr(line, i, 1); continue }
      if (c == "\\") { continue }
      if (c == "\x27" && !in_dq) { in_sq = !in_sq; continue }
      if (c == "\"" && !in_sq)  { in_dq = !in_dq; continue }
      if (c == "[" || c == "]" || c == "{" || c == "}") { continue }
      if (c == "\t") { out = out (tab_mode == "space" ? " " : c); continue }
      if (!in_sq && !in_dq && c ~ /[;|&`()]/) { out = out "\n"; continue }
      out = out c
    }
    if (in_sq || in_dq) printf "%s ", out; else print out
  }'

# Push-only lexer preserves empty quoted words, separates redirection syntax from Git argv, and
# keeps a substitution inside the shell word it is glued to (`--opt=$(x)y` is one word) and
# treats one inside double quotes as live (only single quotes make it literal); the
# substitution body is emitted separately as NEST for recursive scanning.
# shellcheck disable=SC2016 # AWK source is intentionally a single-quoted literal.
_push_token_awk='
  function emit_word() {
    if (!word_started) return
    if (redirect_target) redirect_target = 0
    else print "WORD\t" word
    word = ""; word_started = 0
  }
  function emit_separator() {
    emit_word()
    print "SEP"
  }
  function begin_redirect() {
    if (word_started && word ~ /^[0-9]*$/) {
      word = ""; word_started = 0
    } else emit_word()
    redirect_target = 1
  }
  BEGIN { in_sq = 0; in_dq = 0; escaped = 0; word = ""; word_started = 0; redirect_target = 0 }
  {
    line = $0; n = length(line)
    for (i = 1; i <= n; i++) {
      c = substr(line, i, 1)
      if (escaped) {
        word = word c; word_started = 1; escaped = 0
        continue
      }
      if (c == "\\" && !in_sq) {
        escaped = 1; word_started = 1
        continue
      }
      if (c == "\047" && !in_dq) {
        in_sq = !in_sq; word_started = 1
        continue
      }
      if (c == "\"") {
        if (!in_sq) { in_dq = !in_dq; word_started = 1; continue }
      }
      if (c == "\\") continue
      live_sub = !in_sq && (c == "`" || (c == "$" && substr(line, i + 1, 1) == "("))
      if ((in_sq || in_dq) && !live_sub) {
        word = word c; word_started = 1
        continue
      }
      if (c == "\t") {
        print "TAB"
        emit_word()
        continue
      }
      if (c ~ /[[:space:]]/) {
        emit_word()
        continue
      }
      if (c == "&" && substr(line, i + 1, 1) == ">") {
        begin_redirect()
        i++
        while (i + 1 <= n && substr(line, i + 1, 1) ~ /[><&]/) i++
        continue
      }
      if (c == ">" || c == "<") {
        begin_redirect()
        while (i + 1 <= n && substr(line, i + 1, 1) ~ /[><&]/) i++
        continue
      }
      if (c == "$" && substr(line, i + 1, 1) == "(") {
        subtext = ""; sub_depth = 1; sub_sq = 0; sub_dq = 0
        i += 2
        for (; i <= n; i++) {
          sc = substr(line, i, 1)
          if (sc == "\\" && !sub_sq) {
            subtext = subtext sc
            if (i < n) { i++; subtext = subtext substr(line, i, 1) }
            continue
          }
          if (sc == "\047" && !sub_dq) { sub_sq = !sub_sq; subtext = subtext sc; continue }
          if (sc == "\"" && !sub_sq) { sub_dq = !sub_dq; subtext = subtext sc; continue }
          if (!sub_sq && !sub_dq && sc == "(") { sub_depth++; subtext = subtext sc; continue }
          if (!sub_sq && !sub_dq && sc == ")") {
            sub_depth--
            if (sub_depth == 0) break
            subtext = subtext sc
            continue
          }
          subtext = subtext sc
        }
        if (sub_depth == 0) print "NEST\t" subtext
        word = word dyn; word_started = 1
        continue
      }
      if (c == "`") {
        subtext = ""
        i++
        for (; i <= n; i++) {
          sc = substr(line, i, 1)
          if (sc == "\\" && i < n) {
            subtext = subtext sc
            i++; subtext = subtext substr(line, i, 1)
            continue
          }
          if (sc == "`") break
          subtext = subtext sc
        }
        if (i <= n) print "NEST\t" subtext
        word = word dyn; word_started = 1
        continue
      }
      if (c ~ /[;|&()]/) {
        emit_separator()
        continue
      }
      if (c == "[" || c == "]" || c == "{" || c == "}") continue
      word = word c; word_started = 1
    }
    if (in_sq || in_dq) {
      word = word " "; word_started = 1
    } else emit_separator()
  }
  END { emit_word() }
'

# The active segment is held in globals because Bash 3.2 has no namerefs.
# `scan_force_push_text` resets them at every lexical separator.
_push_tokens=()
_push_saw_tab=0
_DYNAMIC_TOKEN=__SWB_DYNAMIC_SUBSTITUTION__

_classify_force_push_segment() {
  local _prefix _t push_text
  local _i=0 _git_index=-1 _prefix_ok=1 _prefix_args=0 _found_git=0
  local _has_force=0 _has_refspec=0 _pushes_all_refs=0 _seen_positional=0 _has_dynamic=0 _has_context=0
  local _consume_next=0 _seen_push=0 _global_value=0 _context_value=0

  (( ${#_push_tokens[@]} )) || return
  for _prefix in "${_push_tokens[@]}"; do
    case "$_prefix" in
      git|*/git) _found_git=1; break ;;
      [[:alpha:]_][[:alnum:]_]*=*) _prefix_args=1 ;;
      sudo|env|time|nice|nohup|command|exec|xargs|timeout|watch|ssh|bash|sh|zsh|dash|eval|rtk|\
      docker|podman|kubectl|su|setsid|stdbuf|flock|script|*/rtk|*/docker|*/podman|*/kubectl)
        _prefix_args=1 ;;
      '!'|if|while|until|do|then) ;;
      -*) (( _prefix_args )) || _prefix_ok=0 ;;
      *) (( _prefix_args )) || _prefix_ok=0 ;;
    esac
    _i=$((_i + 1))
  done
  (( _push_saw_tab )) && _prefix_ok=1
  (( _found_git && _prefix_ok )) || return
  _git_index=$_i

  for ((_i = _git_index; _i < ${#_push_tokens[@]}; _i++)); do
    _t=${_push_tokens[_i]}
    if (( _seen_push == 0 )); then
      if (( _global_value )); then
        (( _context_value && ${#_t} )) && _has_context=1
        _global_value=0
        _context_value=0
        continue
      fi
      case "$_t" in
        push) _seen_push=1 ;;
        -c|--config|--config-env|--exec-path|--namespace)
          _global_value=1 ;;
        -C|--git-dir|--work-tree)
          _global_value=1; _context_value=1 ;;
        --git-dir=*|--work-tree=*|-C?*) _has_context=1 ;;
        --config=*|--config-env=*|--exec-path=*|--namespace=*|-c*) ;;
        -*) ;;
        *) ;;
      esac
      continue
    fi
    if (( _consume_next )); then
      case "$_t" in
        --force|-f) _has_force=1 ;;
        --all) _pushes_all_refs=1 ;;
        --mirror) _has_force=1; _pushes_all_refs=1 ;;
        -*) [[ "$_t" != --* && "$_t" == *f* ]] && _has_force=1 ;;
      esac
      _consume_next=0
      continue
    fi
    [[ "$_t" != -* && "$_t" == *"$_DYNAMIC_TOKEN"* ]] && _has_dynamic=1
    case "$_t" in
      --force|-f) _has_force=1 ;;
      --all) _pushes_all_refs=1 ;;
      --mirror) _has_force=1; _pushes_all_refs=1 ;;
      --force-with-lease*|--force-if-includes|--tags|--follow-tags|--prune|--thin|--atomic|\
      --no-verify|--dry-run|--porcelain|-q|--quiet|-v|--verbose|--progress|--no-progress|\
      -u|--set-upstream|-d|--delete|--signed|--no-signed|-n) ;;
      --*=*) ;;
      -*)
        if [[ "$_t" != --* && "$_t" == *f* ]]; then
          _has_force=1
        elif [[ "$_t" == -[[:alnum:]][[:alnum:]]* ]]; then
          :
        else
          _consume_next=1
        fi ;;
      *:*) _has_refspec=1 ;;
      *) if (( _seen_positional )); then _has_refspec=1; else _seen_positional=1; fi ;;
    esac
  done
  (( _has_force )) || return
  if (( _pushes_all_refs )); then
    printf 'BLOCK\tall-refs\n'
    return
  fi
  if (( _has_dynamic || (_has_context && _has_refspec == 0) )); then
    printf 'BLOCK\tdynamic-destination\n'
    return
  fi
  push_text=$(printf ' %s' "${_push_tokens[@]}")
  if printf '%s\n' "$push_text" | grep -Eq \
    '(^|[[:space:]]|:)(refs/heads/)?(main|master|release/[^[:space:]:]*)([[:space:]]|:|$)'; then
    printf 'BLOCK\tprotected-ref\n'
    return
  fi
  (( _has_refspec )) || printf 'CHECK_CURRENT\n'
}

MAX_PUSH_SCAN_DEPTH=4

_scan_nested_text() {
  local _nested_text=$1 _nested_depth=$2
  # `${arr[@]+...}` keeps an empty array from tripping `set -u` on bash 3.2.
  local -a _saved_tokens=(${_push_tokens[@]+"${_push_tokens[@]}"})
  local _saved_saw_tab=$_push_saw_tab
  scan_force_push_text "$_nested_text" "$((_nested_depth + 1))"
  _push_tokens=(${_saved_tokens[@]+"${_saved_tokens[@]}"})
  _push_saw_tab=$_saved_saw_tab
}

_scan_known_wrapper_body() {
  local _depth=$1 _i _wrapper_index=-1 _body_index=-1 _token _body=""
  (( ${#_push_tokens[@]} )) || return
  for ((_i = 0; _i < ${#_push_tokens[@]}; _i++)); do
    case "${_push_tokens[_i]}" in bash|sh|zsh|dash|su|ssh|eval) _wrapper_index=$_i; break ;; esac
  done
  (( _wrapper_index >= 0 )) || return

  case "${_push_tokens[_wrapper_index]}" in
    bash|sh|zsh|dash|su)
      for ((_i = _wrapper_index + 1; _i < ${#_push_tokens[@]}; _i++)); do
        if [[ "${_push_tokens[_i]}" == -c ]]; then
          _body_index=$((_i + 1))
          break
        fi
      done
      ;;
    ssh)
      _i=$((_wrapper_index + 1))
      while ((_i < ${#_push_tokens[@]})); do
        case "${_push_tokens[_i]}" in
          -p|-l|-i|-o|-F|-J|-S|-W) _i=$((_i + 2)) ;;
          -*) _i=$((_i + 1)) ;;
          *) _body_index=$((_i + 1)); break ;;
        esac
      done
      ;;
    eval)
      _body_index=$((_wrapper_index + 1))
      ;;
  esac
  (( _body_index >= 0 && _body_index < ${#_push_tokens[@]} )) || return
  if [[ "${_push_tokens[_wrapper_index]}" == bash || "${_push_tokens[_wrapper_index]}" == sh || "${_push_tokens[_wrapper_index]}" == zsh || "${_push_tokens[_wrapper_index]}" == dash || "${_push_tokens[_wrapper_index]}" == su ]]; then
    _body=${_push_tokens[_body_index]}
  else
    for ((_i = _body_index; _i < ${#_push_tokens[@]}; _i++)); do
      _body="$_body${_body:+ }${_push_tokens[_i]}"
    done
  fi
  _scan_nested_text "$_body" "$_depth"
}

scan_force_push_text() {
  local _scan_text=$1 _scan_depth=${2:-0} _kind _value
  if (( _scan_depth >= MAX_PUSH_SCAN_DEPTH )); then
    if printf '%s\n' "$_scan_text" | tr -d "'\"" | grep -Eq \
      'git[[:space:]]+push([[:space:]].*)?([[:space:]]|^)(--force|-[[:alnum:]]*f[[:alnum:]]*)([[:space:]]|$)'; then
      printf 'BLOCK\tindeterminate\n'
    fi
    return
  fi
  _push_tokens=()
  _push_saw_tab=0
  while IFS=$'\t' read -r _kind _value; do
    case "$_kind" in
      WORD) _push_tokens+=("$_value") ;;
      NEST) _scan_nested_text "$_value" "$_scan_depth" ;;
      TAB) _push_saw_tab=1 ;;
      SEP)
        _scan_known_wrapper_body "$_scan_depth"
        _classify_force_push_segment
        _push_tokens=()
        _push_saw_tab=0
        ;;
    esac
  done < <(printf '%s' "$_scan_text" | awk -v dyn="$_DYNAMIC_TOKEN" "$_push_token_awk")
  _scan_known_wrapper_body "$_scan_depth"
  _classify_force_push_segment
}

while IFS=$'\t' read -r _policy _reason; do
  case "$_policy" in
    BLOCK)
      case "$_reason" in
        all-refs) echo 'BLOCKED: force push of all refs may update protected branches' >&2 ;;
        *) echo 'BLOCKED: force push to protected branch (main/master/release/*)' >&2 ;;
      esac
      exit 2
      ;;
    CHECK_CURRENT)
      branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
      case "$branch" in
        main|master|release/*)
          echo "BLOCKED: force push of current protected branch '$branch' (implicit upstream)" >&2
          exit 2
          ;;
        '')
          echo 'BLOCKED: unable to resolve branch for implicit force push' >&2
          exit 2
          ;;
      esac
      ;;
  esac
done < <(scan_force_push_text "$_bj")

if echo "$norm" | grep -Eq 'git[[:space:]]+reset[[:space:]]+--hard'; then
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
  case "$branch" in
    main|master|release/*)
      echo "BLOCKED: git reset --hard on protected branch '$branch'" >&2
      exit 2
      ;;
  esac
fi

# Nested non-interactive `pi` session — subagent recursion guard. Segment-scoped:
# a `pi` command token and a -p/--print flag must appear in the SAME segment, so everyday
# commands like `git log -p && pi list` stay allowed. Segments split on real separators
# (;|&\n) plus substitution boundaries (`()) so $(pi -p …) is isolated; a literal tab folds
# to a space (not a break) so `pi<TAB>-p` can't hide across a fake boundary. The whole pass
# is quote-aware (same in_sq/in_dq state-machine idiom as the comment-stripper above) so a
# separator character INSIDE a quoted argument (e.g. `pi -m ";" -p x`) is never mistaken for
# a real segment break — folding separators before stripping quotes was the bug in an
# earlier version of this block. A backslash-ESCAPED separator (e.g. `pi \; -p x`, a literal
# argument byte in real bash) must not be treated as a break either — an escaping backslash
# consumes the NEXT character as a literal and neither is re-examined against the separator
# or quote-toggle rules, so escaping a `;`/`&`/`(` etc. can't fake a segment boundary and
# escaping a quote can't fake a close. A REAL (unescaped) newline inside an open quote is
# also just a literal argument byte (e.g. a multi-line -m message) — awk's own per-record
# boundary is `\n` unconditionally, so the record split itself must be gated on quote state
# too, or a multi-line quoted argument fakes a break the exact same way a quoted `;` would.
# Backslash-continuation joining already happened upstream (in $_bj, shared with the fast
# gate above), so this pass doesn't need its own. The command-name token is matched
# case-insensitively below (grep -i on the first stage only) for the same reason the fast
# gate above does — "Pi"/"PI" resolve to the same binary as "pi" on a case-insensitive
# filesystem; the -p/--print flag check stays case-sensitive.
case "$norm" in
  [Pp][Ii]\ *|*\ [Pp][Ii]\ *|*/[Pp][Ii]\ *)
    pi_seg=$(printf '%s' "$_bj" | awk -v tab_mode=space "$_segment_awk")
    if printf '%s\n' "$pi_seg" | grep -iE '(^|[[:space:]])([^[:space:]]*/)?pi[[:space:]]' \
       | grep -Eq '(^|[[:space:]])(-p|--print)([[:space:]]|=|$)'; then
      echo 'BLOCKED: nested non-interactive pi session (subagent recursion guard)' >&2
      exit 2
    fi
    ;;
esac

exit 0
