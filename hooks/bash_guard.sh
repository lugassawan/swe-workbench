#!/usr/bin/env bash
# PreToolUse:Bash guard — block destructive commands and short-circuit safe ones.
#
# Blocks:
#   - rm -rf against /, /*, ~, $HOME, /Users[/<user>], /home[/<user>]
#   - git push --force / -f to main/master/release/*
#   - a force push with a dynamic destination or flag, a target in another repository (-C,
#     --git-dir, --work-tree), or nesting too deep to scan, on any branch
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
# Accepted gaps: brace expansion, glob refspecs and unique-prefix long options; a bare substitution
# that is the force flag with an implicit destination; function/coproc NAME bodies; unlisted wrappers.
# --force-with-lease/--force-if-includes intentionally unblocked (#163); the push scan lexes quotes
# (quoted text is literal, substitutions are scanned); a remote literally
# named main/master over-blocks. The push-token scan trusts a small allowlist of known
# BOOLEAN-only push flags and defensively consumes the next token for any other `-*` flag
# (assumes it takes a separate-word value, e.g. `-o ci.skip`) so an unknown flag's value can never
# be miscounted as the remote/refspec (#501 senior-engineer consult); an unrecognized flag that
# actually takes NO value over-blocks by one token (fail-safe direction).
# Quotes are stripped before matching (same fail-safe direction as that over-block
# above), so a `pi -p` mention inside an unrelated quoted string (e.g. a commit message) can
# over-block too — accepted, not special-cased.

set -u

if ! cmd=$(jq -r '.tool_input.command // ""'); then
  echo 'bash_guard: jq parse error — blocking by default' >&2
  exit 2
fi

# A preprocessing program that cannot run (awk or tr missing, killed) must not read as "nothing to
# guard": every stage below captures its output through this on failure.
_fail_closed() {
  echo "BLOCKED: guard preprocessing failed ($1) — blocking by default" >&2
  exit 2
}

# The awk stages are quadratic on long text, so past this size the comment stripper and the
# lexer are skipped and the push scan answers with its coarse grep.
MAX_EXACT_SCAN_BYTES=65536
_oversize=0
(( ${#cmd} > MAX_EXACT_SCAN_BYTES )) && _oversize=1

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
# shellcheck disable=SC2016 # AWK source is intentionally a single-quoted literal.
_comment_awk='
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
}'
if (( _oversize )); then
  _nc=$cmd
else
  _nc=$(printf '%s' "$cmd" | LC_ALL=C awk "$_comment_awk") || _fail_closed awk
fi

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
_bj=$(printf '%s' "$_nc" | LC_ALL=C awk '
{
  line = $0; ll = length(line); nb = 0
  while (nb < ll && substr(line, ll - nb, 1) == "\\") nb++
  if (nb % 2 == 1) printf "%s", substr(line, 1, ll - 1); else print line
}') || _fail_closed awk

# Normalise separators AND newlines/tabs/backticks to spaces so rm/git after
# ; | & \n \t \` are still detected — the fast-gate `case` and the grep
# detectors must share ONE separator alphabet (gate saw ';|&', grep saw
# [[:space:]]).
# shellcheck disable=SC2016  # backtick in tr's SET1 is a literal char, not command substitution
_norm=$(printf '%s' "$_bj" | tr ';|&\n\t`' '      ') || _fail_closed tr

# Fully normalise BEFORE the fast gate, not after: turning "(" and ")" into SPACES (not
# deleting them) handles $(...), <(...), >(...), and bare (...) uniformly, since whatever
# preceded "(" no longer occupies the whitespace-or-start position the anchor regex requires.
# Deleting quotes/brackets/backslashes closes quote-wrapped/backslash-escaped rm ("rm", 'rm',
# \rm). Gate and detector now both run on this SAME normalized text ($norm), closing the same
# class of gate/detector divergence for quote-wrapped rm.
norm=$(printf '%s' "$_norm" | tr '()' '  ' | tr -d "'\"[]{}\\\\") || _fail_closed tr

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

# Quote- and escape-aware shell segmenter for the pi detector (the push scan has its own
# lexer below). A literal tab folds to a space.
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
      if (c == "\t") { out = out " "; continue }
      if (!in_sq && !in_dq && c ~ /[;|&`()]/) { out = out "\n"; continue }
      out = out c
    }
    if (in_sq || in_dq) printf "%s ", out; else print out
  }'

# Push-only lexer: redirects are syntax; empty quoted words and live substitutions stay in their word.
# shellcheck disable=SC2016 # AWK source is intentionally a single-quoted literal.
_push_token_awk='
  function emit_word() {
    if (!word_started) return
    if (redirect_target) { if (here_string) print "HERE\t" word; redirect_target = 0; here_string = 0 }
    else print "WORD\t" word
    word = ""; word_started = 0
  }
  function finish_subst() {
    print "NEST\t" subtext
    word = word dyn; word_started = 1
  }
  function unquoted(s,   r, k, ch, q, e) {
    r = ""; q = ""; e = 0
    for (k = 1; k <= length(s); k++) {
      ch = substr(s, k, 1)
      if (e) { e = 0; continue }
      if (q == "") {
        if (ch == "\\") { e = 1; continue }
        if (ch == "\047" || ch == "\"") { q = ch; r = r "Q"; continue }
        r = r ch
      } else if (q == "\"" && ch == "\\") { e = 1 }
      else if (ch == q) { q = "" }
    }
    return r
  }
  function emit_separator() {
    emit_word()
    redirect_target = 0; here_string = 0
    print "SEP"
  }
  function begin_redirect() {
    if (word_started && word ~ /^[0-9]*$/) {
      word = ""; word_started = 0
    } else emit_word()
    redirect_target = 1
  }
  BEGIN { in_sq = 0; in_dq = 0; escaped = 0; word = ""; word_started = 0; redirect_target = 0; here_string = 0; hd_nl = 0; hd_to = 0 }
  { buf = (NR == 1) ? $0 : buf "\n" $0 }
  END {
    line = buf; gsub(/\001/, "\n", line); n = length(line)
    for (i = 1; i <= n; i++) {
      c = substr(line, i, 1)
      if (hd_nl > 0 && i > hd_nl) hd_nl = 0
      if (c == "\n") {
        escaped = 0
        if (in_sq || in_dq) { word = word "\001"; word_started = 1 } else {
          emit_separator()
          if (hd_nl > 0 && i == hd_nl) { i = hd_to; hd_nl = 0 }
        }
        continue
      }
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
      if (c == "\\") { word = word c; word_started = 1; continue }
      live_sub = !in_sq && (c == "`" || (c == "$" && substr(line, i + 1, 1) == "("))
      if ((in_sq || in_dq) && !live_sub) {
        if (c == "\t") print "TAB"
        word = word c; word_started = 1
        continue
      }
      if (c == "\t") {
        print "TAB"
        emit_word()
        continue
      }
      if (c ~ /[ \t\r\f\v]/) {
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
        if (substr(line, i + 1, 1) == "(") { emit_word(); continue }
        if (c == "<" && substr(line, i, 3) == "<<<") here_string = 1
        if (c == "<" && substr(line, i, 2) == "<<" && substr(line, i, 3) != "<<<" && hd_nl == 0) {
          # a quoted-delimiter heredoc whose start line ends there (a pipe or && would let the
          # body reach another consumer) is data: skip it so its quotes cannot desync the lexer
          hj = i + 2; hstrip = 0
          if (substr(line, hj, 1) == "-") { hstrip = 1; hj++ }
          while (substr(line, hj, 1) ~ /[ \t]/) hj++
          hq = substr(line, hj, 1); hid = ""; hend = 0
          if ((hq == "\047" || hq == "\"") && match(substr(line, hj + 1), /^[A-Za-z_][A-Za-z0-9_]*/)) {
            hid = substr(line, hj + 1, RLENGTH)
            hend = hj + 1 + RLENGTH
            if (substr(line, hend, 1) != hq) hid = ""; else hend++
          } else if (hq == "\\" && match(substr(line, hj + 1), /^[A-Za-z_][A-Za-z0-9_]*/)) {
            hid = substr(line, hj + 1, RLENGTH)
            hend = hj + 1 + RLENGTH
          }
          if (hid != "") {
            hnl = index(substr(line, hend), "\n")
            if (hnl > 0 && substr(line, hend, hnl - 1) ~ /^[ \t]*([0-9]*>>?[ \t]*[^ \t|&;<>()`$]+)?[ \t]*$/) {
              hnlpos = hend + hnl - 1
              hbs = hnlpos + 1; hp = hbs; hfound = 0
              while (hp <= n) {
                hx = index(substr(line, hp), "\n")
                if (hx == 0) { hl = substr(line, hp) } else { hl = substr(line, hp, hx - 1) }
                hcmp = hl
                if (hstrip) sub(/^\t+/, "", hcmp)
                if (hcmp == hid) { hfound = 1; break }
                if (hx == 0) break
                hp = hp + hx
              }
              if (hfound) {
                hb = substr(line, hbs, hp - hbs)
                gsub(/\n/, "\001", hb)
                print "HERE\t" hb
                hd_nl = hnlpos
                hd_to = hp + length(hl) - 1
              }
            }
          }
        }
        begin_redirect()
        while (i + 1 <= n && substr(line, i + 1, 1) ~ /[><&|]/) i++
        continue
      }
      if (c == "$" && (substr(line, i + 1, 1) == "\047" || substr(line, i + 1, 1) == "\"")) continue
      if (c == "$" && substr(line, i + 1, 1) == "(") {
        subtext = ""; sub_depth = 1; sub_sq = 0; sub_dq = 0
        i += 2
        for (; i <= n; i++) {
          sc = substr(line, i, 1)
          if (sc == "\n") {
            sc = ";"
            # the output of cat is data only when nothing follows the delimiter (a pipe makes it code)
            # and `cat <<` is real syntax at command position, not text inside a quoted word
            if (!sub_sq && !sub_dq && subtext ~ /<<-?[ \t]*(\047[A-Za-z_][A-Za-z0-9_]*\047|"[A-Za-z_][A-Za-z0-9_]*")[ \t]*$/ && unquoted(subtext) ~ /(^|;|&&|\|\||\()[ \t]*cat[ \t]+<<-?[ \t]*Q[ \t]*$/) {
              match(subtext, /<<-?[ \t]*(\047[A-Za-z_][A-Za-z0-9_]*\047|"[A-Za-z_][A-Za-z0-9_]*")[ \t]*$/)
              hd = substr(subtext, RSTART, RLENGTH)
              if (match(hd, /[\047"][A-Za-z_][A-Za-z0-9_]*[\047"]/)) {
                delim = substr(hd, RSTART + 1, RLENGTH - 2)
                strip_tabs = (hd ~ /<<-/)
                bstart = i + 1; pos = bstart; found = 0
                while (pos <= n) {
                  nl = index(substr(line, pos), "\n")
                  if (nl == 0) { ltxt = substr(line, pos) } else { ltxt = substr(line, pos, nl - 1) }
                  cmp = ltxt
                  if (strip_tabs) sub(/^\t+/, "", cmp)
                  if (cmp == delim) { found = 1; break }
                  if (nl == 0) break
                  pos = pos + nl
                }
                if (found) {
                  hbody = substr(line, bstart, pos - bstart)
                  gsub(/\n/, "\001", hbody)
                  print "HERE\t" hbody
                  i = pos + length(ltxt) - 1
                }
              }
            }
          }
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
        finish_subst()
        continue
      }
      if (c == "`") {
        subtext = ""
        i++
        for (; i <= n; i++) {
          sc = substr(line, i, 1)
          if (sc == "\n") sc = ";"
          if (sc == "\\" && i < n) {
            subtext = subtext sc
            i++; subtext = subtext substr(line, i, 1)
            continue
          }
          if (sc == "`") break
          subtext = subtext sc
        }
        finish_subst()
        continue
      }
      if (c ~ /[;|&()]/) {
        emit_separator()
        continue
      }
      if (c == "[" || c == "]" || c == "{" || c == "}") continue
      word = word c; word_started = 1
    }
    emit_separator()
    print "EOS"
  }
'

# The active segment is held in globals because Bash 3.2 has no namerefs.
# `scan_force_push_text` resets them at every lexical separator.
_push_tokens=()
_push_here=()
_push_subs=()
_push_saw_tab=0
_DYNAMIC_TOKEN=__SWB_DYNAMIC_SUBSTITUTION__
# Set while a wrapper's code operand is re-scanned: everything before `git` there is an argument.
_NESTED_WRAPPER_BODY=0

# Programs that run their remaining arguments as a command: everything after one of them
# is code.
_is_wrapper_prefix() {
  case "$1" in
    sudo|env|time|nice|nohup|command|exec|xargs|timeout|watch|ssh|bash|sh|zsh|dash|ksh|fish|eval|\
    rtk|docker|podman|kubectl|su|setsid|stdbuf|flock|script) return 0 ;;
  esac
  return 1
}

# `git` only names the command when something git-like follows it; `-u git`, `-l git` and a
# `.../git` path argument are values of a wrapper's own options.
_is_git_continuation() {
  case "$1" in
    ''|-*) return 0 ;;
    add|am|annotate|apply|archive|bisect|blame|branch|bundle|cat-file|checkout|cherry|cherry-pick|\
    clean|clone|commit|config|credential|describe|diff|difftool|fast-export|fast-import|fetch|\
    filter-branch|for-each-ref|format-patch|fsck|gc|grep|hash-object|help|init|log|ls-files|\
    ls-remote|ls-tree|maintenance|merge|mergetool|mv|name-rev|notes|pull|push|range-diff|rebase|\
    reflog|remote|repack|replace|request-pull|reset|restore|rev-list|rev-parse|revert|rm|\
    send-email|shortlog|show|show-branch|sparse-checkout|stash|status|submodule|svn|switch|\
    symbolic-ref|tag|update-ref|var|version|worktree) return 0 ;;
  esac
  return 1
}

_is_shell_interpreter() {
  case "$1" in bash|sh|zsh|dash|ksh|fish|su|eval|source|.) return 0 ;; esac
  return 1
}

_classify_force_push_segment() {
  local _prefix _base _t push_text
  local _i=0 _git_index=-1 _prefix_ok=1 _prefix_args=$_NESTED_WRAPPER_BODY _found_git=0
  local _has_force=0 _has_refspec=0 _pushes_all_refs=0 _seen_positional=0 _has_dynamic=0 _has_context=0
  local _consume_next=0 _seen_push=0 _global_value=0 _context_value=0 _dynamic_flag_candidate=0
  local _consume_flag="" _glued_flag_candidate=0 _skip_tok=0 _tail=""
  local _positional_count=0 _first_positional_dynamic=0 _has_colon_refspec=0
  local _flag_cluster_re='^[A-Za-z]*f[A-Za-z]*$'
  local _protected_ref_re='(^|[[:space:]:+])(refs/heads/)?(main|master|release/[^[:space:]:]*)([[:space:]]|:|$)'

  (( ${#_push_tokens[@]} )) || return
  for _prefix in "${_push_tokens[@]}"; do
    if (( ${#_prefix} > 255 )); then _base=$_prefix; else _base=${_prefix##*/}; fi
    [[ "$_base" == *"$_DYNAMIC_TOKEN"?* ]] && _base=${_base##*"$_DYNAMIC_TOKEN"}
    case "$_base" in
      git)
        if _is_git_continuation "${_push_tokens[_i + 1]-}"; then _found_git=1; break; fi
        (( _prefix_args )) || _prefix_ok=0 ;;
      [[:alpha:]_]=*|[[:alpha:]_][[:alnum:]_]*=*) _prefix_args=1 ;;
      '!'|if|while|until|do|then|else|elif|coproc) ;;
      "$_DYNAMIC_TOKEN") ;;
      -exec|-execdir|-ok|-okdir) _prefix_ok=1; _prefix_args=0 ;;
      *)
        if _is_wrapper_prefix "$_base"; then
          _prefix_args=1
        else
          (( _prefix_args )) || _prefix_ok=0
        fi ;;
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
        --al|--all|--b|--br|--bra|--bran|--branc|--branch|--branche|--branches) _pushes_all_refs=1 ;;
        --m|--mi|--mir|--mirr|--mirro|--mirror) _has_force=1; _pushes_all_refs=1 ;;
        -*) [[ "$_t" != --* && "$_t" == *f* ]] && _has_force=1 ;;
      esac
      # a value-taking flag may carry a substitution; any other flag's slot is the destination
      case "$_consume_flag" in
        -o|--push-option|--repo|--receive-pack|--exec|--recurse-submodules) ;;
        *) [[ "$_t" == *"$_DYNAMIC_TOKEN"* ]] && _has_dynamic=1 ;;
      esac
      _consume_next=0
      continue
    fi
    if [[ "$_t" == *"$_DYNAMIC_TOKEN"* ]]; then
      if [[ "$_t" != -* ]]; then
        _has_dynamic=1
        if [[ "$_t" == "$_DYNAMIC_TOKEN"* && "$_t" != *:* ]]; then
          _tail=${_t#"$_DYNAMIC_TOKEN"}
          if [[ -z "$_tail" || "$_tail" == *"$_DYNAMIC_TOKEN"* || "--force" == *"$_tail" \
                || "--mirror" == *"$_tail" ]] || [[ "$_tail" =~ $_flag_cluster_re ]]; then
            _dynamic_flag_candidate=1
            if [[ -n "$_tail" ]]; then _glued_flag_candidate=1; _skip_tok=1; fi
          fi
        fi
      elif [[ "${_t%%=*}" == *"$_DYNAMIC_TOKEN"* ]]; then
        _has_force=1
      fi
    fi
    if (( _skip_tok )); then _skip_tok=0; continue; fi
    [[ "$_t" != -* && ( "$_t" == +* || "$_t" == *:+* ) ]] && _has_force=1
    case "$_t" in
      --force|-f) _has_force=1 ;;
      --al|--all|--b|--br|--bra|--bran|--branc|--branch|--branche|--branches) _pushes_all_refs=1 ;;
      --m|--mi|--mir|--mirr|--mirro|--mirror) _has_force=1; _pushes_all_refs=1 ;;
      --force-with-lease*|--force-if-includes|--tags|--follow-tags|--prune|--thin|--atomic|\
      --no-verify|--dry-run|--porcelain|-q|--quiet|-v|--verbose|--progress|--no-progress|\
      -u|--set-upstream|-d|--delete|--signed|--no-signed|-n|--no-thin|--no-atomic|--verify|\
      --no-*|-4|-6|--ipv4|--ipv6|--) ;;
      --*=*) ;;
      -*)
        if [[ "$_t" != --* && "$_t" == *f* ]]; then
          _has_force=1
        elif [[ "$_t" == -[[:alnum:]][[:alnum:]]* ]]; then
          :
        else
          _consume_next=1
          _consume_flag=$_t
        fi ;;
      '{}'|HEAD|@) ;;
      # a wildcard or the matching refspec ':' / '+:' updates every matching ref
      *\**|:|+:) _has_refspec=1; _pushes_all_refs=1 ;;
      *:*) _has_refspec=1; _has_colon_refspec=1 ;;
      *)
        _positional_count=$((_positional_count + 1))
        if (( _seen_positional )); then
          _has_refspec=1
        else
          _seen_positional=1
          [[ "$_t" == "$_DYNAMIC_TOKEN" ]] && _first_positional_dynamic=1
        fi ;;
    esac
  done
  push_text=$(printf ' %s' "${_push_tokens[@]}")
  # A substitution-led word that can finish a force flag counts next to a literal protected ref;
  # a glued one with no refspec checks the current branch (a bare one is a normal push).
  if (( ! _has_force && _dynamic_flag_candidate )); then
    if printf '%s\n' "$push_text" | grep -Eq "$_protected_ref_re"; then
      _has_force=1
    elif (( _glued_flag_candidate && ! _has_refspec )); then
      printf 'CHECK_CURRENT_MAYBE\n'
      return
    fi
  fi
  # A bare substitution first may itself be the force flag; with the destination implicit
  # (at most one literal positional after it) only the current branch is at stake.
  if (( ! _has_force && _first_positional_dynamic && _positional_count <= 2 && ! _has_colon_refspec )); then
    printf 'CHECK_CURRENT_MAYBE\n'
    return
  fi
  (( _has_force )) || return
  if (( _pushes_all_refs )); then
    printf 'BLOCK\tall-refs\n'
    return
  fi
  if (( _has_dynamic )); then
    printf 'BLOCK\tdynamic-destination\n'
    return
  fi
  if (( _has_context && _has_refspec == 0 )); then
    printf 'BLOCK\tcontext-destination\n'
    return
  fi
  if printf '%s\n' "$push_text" | grep -Eq "$_protected_ref_re"; then
    printf 'BLOCK\tprotected-ref\n'
    return
  fi
  (( _has_refspec )) || printf 'CHECK_CURRENT\n'
}

MAX_PUSH_SCAN_DEPTH=4
# Why the coarse grep ran instead of the lexer: nesting too deep (default) or text too large.
_limit_reason=indeterminate
(( _oversize )) && _limit_reason=oversize

_scan_nested_text() {
  local _nested_text=$1 _nested_depth=$2
  # `${arr[@]+...}` keeps an empty array from tripping `set -u` on bash 3.2.
  local -a _saved_tokens=(${_push_tokens[@]+"${_push_tokens[@]}"})
  local -a _saved_here=(${_push_here[@]+"${_push_here[@]}"})
  local -a _saved_subs=(${_push_subs[@]+"${_push_subs[@]}"})
  local _saved_saw_tab=$_push_saw_tab
  scan_force_push_text "$_nested_text" "$((_nested_depth + 1))"
  _push_tokens=(${_saved_tokens[@]+"${_saved_tokens[@]}"})
  _push_here=(${_saved_here[@]+"${_saved_here[@]}"})
  _push_subs=(${_saved_subs[@]+"${_saved_subs[@]}"})
  _push_saw_tab=$_saved_saw_tab
}

# A word holding whitespace or a quoted newline is a candidate command string.
_has_code_text() {
  [[ "$1" == *[[:space:]]* || "$1" == *$'\001'* ]]
}

_scan_wrapper_operand() {
  local _saved_seed=$_NESTED_WRAPPER_BODY
  _NESTED_WRAPPER_BODY=1
  _scan_nested_text "$1" "$2"
  _NESTED_WRAPPER_BODY=$_saved_seed
}

# After a wrapper prefix every quoted string before the first `git` word is code (a shell's
# `$0` args excepted); words after `git` are data unless git itself runs them.
_scan_known_wrapper_body() {
  local _depth=$1 _n=${#_push_tokens[@]} _i _j _k _m _tok _base _body _args
  local _p=-1 _g=-1 _after=0 _end _runner=0 _prev="" _consumer=0 _isgit _cmdword=0
  for ((_i = 0; _i < _n; _i++)); do
    _tok=${_push_tokens[_i]}
    if (( ${#_tok} > 255 )); then _base=$_tok; else _base=${_tok##*/}; fi
    [[ "$_base" == *"$_DYNAMIC_TOKEN"?* ]] && _base=${_base##*"$_DYNAMIC_TOKEN"}
    _is_shell_interpreter "$_base" && _consumer=1
    case "$_tok" in
      -exec|-execdir|-ok|-okdir) _p=-1; _g=-1; _after=0; continue ;;
    esac
    (( _g < 0 )) || continue
    _isgit=0
    if [[ "$_base" == git ]] && _is_git_continuation "${_push_tokens[_i + 1]-}"; then _isgit=1; fi
    case "$_base" in
      git)
        if (( _isgit )); then
          _g=$_i
        elif (( ! _after && ! _NESTED_WRAPPER_BODY && ! _push_saw_tab )); then
          _g=$_n
        fi ;;
      [[:alpha:]_]=*|[[:alpha:]_][[:alnum:]_]*=*)
        # an assignment prefix makes everything after it arguments
        (( _p >= 0 )) || _p=$_i
        _after=1 ;;
      '!'|if|while|until|do|then|else|elif|coproc|"$_DYNAMIC_TOKEN") ;;
      *)
        if _is_wrapper_prefix "$_base"; then
          (( _p >= 0 )) || _p=$_i
          _after=1
        elif (( ! _after && ! _NESTED_WRAPPER_BODY && ! _push_saw_tab )); then
          _g=$_n
        fi ;;
    esac
  done
  (( _g < _n )) || _g=-1
  for ((_i = 0; _i < _n; _i++)); do
    case "${_push_tokens[_i]}" in
      [[:alpha:]_]=*|[[:alpha:]_][[:alnum:]_]*=*) continue ;;
      "$_DYNAMIC_TOKEN") _cmdword=1 ;;
    esac
    break
  done

  # A body that was itself handed to a wrapper has no visible prefix, but is still all arguments.
  # A tab anywhere in the segment, quoted or not, also makes the segment a wrapper call.
  if (( _p >= 0 || _NESTED_WRAPPER_BODY || _push_saw_tab )); then
    _end=$(( _g >= 0 ? _g : _n ))
    for ((_i = (_p >= 0 ? _p : 0); _i < _end; _i++)); do
      _tok=${_push_tokens[_i]}
      if (( ${#_tok} > 255 )); then _base=$_tok; else _base=${_tok##*/}; fi
      case "$_base" in
        bash|sh|zsh|dash|ksh|fish|su)
          for ((_j = _i + 1; _j < _n; _j++)); do
            case "${_push_tokens[_j]}" in
              --command=*)
                _scan_wrapper_operand "${_push_tokens[_j]#*=}" "$_depth"
                break ;;
              -c*|--command|-[!-]*c*)
                for ((_k = _j + 1; _k < _n; _k++)); do
                  if _has_code_text "${_push_tokens[_k]}"; then
                    _body=${_push_tokens[_k]}
                    _scan_wrapper_operand "$_body" "$_depth"
                    # arguments after the script are $0 $1 ...; rescan them in place when it uses them
                    case "$_body" in
                      *\$[0-9@*]*|*\$\{[0-9@*]*)
                        _args=""
                        for ((_m = _k + 1; _m < _n; _m++)); do _args="$_args ${_push_tokens[_m]}"; done
                        [[ -n "$_args" ]] && _scan_wrapper_operand "$_body$_args" "$_depth" ;;
                    esac
                    break
                  fi
                done
                break ;;
            esac
          done
          _i=$_end ;;
        *)
          if (( _i > _p )) && _has_code_text "$_tok"; then
            _scan_wrapper_operand "$_tok" "$_depth"
          fi ;;
      esac
    done
  fi

  if (( _g >= 0 )); then
    for ((_i = _g + 1; _i < _n; _i++)); do
      _tok=${_push_tokens[_i]}
      case "$_tok" in
        foreach|filter-branch|run|-x|--exec|--exec=*|--extcmd|--extcmd=*|--tree-filter|\
        --index-filter|--msg-filter|--env-filter|--commit-filter|--parent-filter|--tag-name-filter|\
        --upload-pack|--upload-pack=*|--receive-pack|--receive-pack=*|-O?*|ext::*)
          _runner=1 ;;
      esac
      if [[ "$_prev" == -c || "$_tok" == -c?* ]] && _has_code_text "$_tok"; then
        _base=${_tok#*=}
        _scan_wrapper_operand "${_base#!}" "$_depth"
      fi
      _prev=$_tok
    done
    if (( _runner )); then
      for ((_i = _g + 1; _i < _n; _i++)); do
        _tok=${_push_tokens[_i]}
        _has_code_text "$_tok" || continue
        if [[ "$_tok" == -O?* ]]; then _tok=${_tok#-O}
        elif [[ "$_tok" == -*=* ]]; then _tok=${_tok#*=}; fi
        _scan_wrapper_operand "$_tok" "$_depth"
      done
    fi
  fi

  for _body in ${_push_subs[@]+"${_push_subs[@]}"}; do
    if (( _p >= 0 || _cmdword )); then _scan_wrapper_operand "$_body" "$_depth"
    else _scan_nested_text "$_body" "$_depth"; fi
  done
  # A here-string is code only for a shell or a wrapper running one; `cat <<< 'text'` is data.
  if (( _p >= 0 || _consumer || _cmdword )); then
    for _body in ${_push_here[@]+"${_push_here[@]}"}; do
      _scan_wrapper_operand "$_body" "$_depth"
    done
  fi
}

scan_force_push_text() {
  local _scan_text=$1 _scan_depth=${2:-0} _kind _value _lex_ok=0
  if (( _scan_depth >= MAX_PUSH_SCAN_DEPTH )); then
    if printf '%s\n' "$_scan_text" | tr -d "'\"\\\\[]{}" | tr '()`' '   ' | grep -Eq \
      'git([[:space:]].*)?[[:space:]]push([[:space:]].*)?[[:space:]](--force|--mirror|-[[:alnum:]]*f[[:alnum:]]*|\+[^[:space:]]+)([[:space:];&|()`]|$)'; then
      printf 'BLOCK\t%s\n' "$_limit_reason"
    fi
    return
  fi
  _push_tokens=()
  _push_here=()
  _push_subs=()
  _push_saw_tab=0
  while IFS=$'\t' read -r _kind _value; do
    case "$_kind" in
      WORD) _push_tokens+=("$_value") ;;
      NEST) _push_subs+=("$_value") ;;
      HERE) _push_here+=("$_value") ;;
      TAB) _push_saw_tab=1 ;;
      EOS) _lex_ok=1 ;;
      SEP)
        _scan_known_wrapper_body "$_scan_depth"
        _classify_force_push_segment
        _push_tokens=()
        _push_here=()
        _push_subs=()
        _push_saw_tab=0
        ;;
    esac
  done < <(printf '%s' "$_scan_text" | LC_ALL=C awk -v dyn="$_DYNAMIC_TOKEN" "$_push_token_awk")
  _scan_known_wrapper_body "$_scan_depth"
  _classify_force_push_segment
  (( _lex_ok )) || printf 'BLOCK\tscan-failed\n'
}

# The scanner ends with DONE; a missing sentinel means it died mid-scan, which must not read as "clean".
_scan_done=0
while IFS=$'\t' read -r _policy _reason; do
  case "$_policy" in
    DONE) _scan_done=1 ;;
    BLOCK)
      case "$_reason" in
        all-refs) echo 'BLOCKED: force push of all refs may update protected branches' >&2 ;;
        scan-failed) echo 'BLOCKED: force-push scan did not complete (internal error)' >&2 ;;
        dynamic-destination) echo 'BLOCKED: force push with a dynamic destination or flag cannot be checked; spell the branch literally or use --force-with-lease' >&2 ;;
        context-destination) echo 'BLOCKED: force push into another repository (-C/--git-dir/--work-tree) cannot be attributed to a branch; name the refspec literally' >&2 ;;
        indeterminate) echo 'BLOCKED: force push nested too deeply to scan; spell the push directly or use --force-with-lease' >&2 ;;
        oversize) echo 'BLOCKED: force push in a command too large to scan exactly; split the command or use --force-with-lease' >&2 ;;
        *) echo 'BLOCKED: force push to protected branch (main/master/release/*)' >&2 ;;
      esac
      exit 2
      ;;
    CHECK_CURRENT_MAYBE)
      branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
      case "$branch" in
        main|master|release/*)
          echo "BLOCKED: this may be a force push of current protected branch '$branch' (a substitution can spell the force flag; spell it literally or use --force-with-lease)" >&2
          exit 2
          ;;
      esac
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
done < <(scan_force_push_text "$_bj" "$(( _oversize ? MAX_PUSH_SCAN_DEPTH : 0 ))"; printf 'DONE\n')
if (( ! _scan_done )); then
  echo 'BLOCKED: force-push scan did not complete (internal error)' >&2
  exit 2
fi

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
    # Oversize text skips the segmenter: `pi` and a print flag anywhere in it count as one segment.
    if (( _oversize )); then
      pi_seg=$norm
    else
      pi_seg=$(printf '%s' "$_bj" | LC_ALL=C awk "$_segment_awk") || _fail_closed awk
    fi
    if printf '%s\n' "$pi_seg" | grep -iE '(^|[[:space:]])([^[:space:]]*/)?pi[[:space:]]' \
       | grep -Eq '(^|[[:space:]])(-p|--print)([[:space:]]|=|$)'; then
      echo 'BLOCKED: nested non-interactive pi session (subagent recursion guard)' >&2
      exit 2
    fi
    ;;
esac

exit 0
