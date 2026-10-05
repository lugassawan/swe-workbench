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
# Out of scope: ${HOME} brace-form; ANSI-C $'...' quoting; path normalization via .. traversal (attribution treats .. components as unresolvable, keeping the legacy check);
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

_payload=$(cat)
if ! cmd=$(printf '%s' "$_payload" | jq -r '.tool_input.command // ""'); then
  echo 'bash_guard: jq parse error — blocking by default' >&2
  exit 2
fi
# Base dir for attribution: the harness-supplied session cwd when the payload carries an
# absolute one, else the guard process cwd (the pre-attribution behavior).
_base=$(printf '%s' "$_payload" | jq -r '.cwd // ""' 2>/dev/null)
[[ "$_base" == /* ]] || _base=$PWD
_checked=$_base; [[ "$PWD" == "$_base" ]] || _checked="$_base and $PWD"   # dirs the uncertain fallback consults
# Allow-side attribution note, emitted as one `systemMessage` stdout line at the final
# exit 0 (never when a check blocks). docs/hooks.md §2.
_warn_reason=''

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

# Attribution stream: one CONF:<abs-path> | UNCERTAIN line per segment, in _segment_awk
# order (docs/hooks.md §2). UNCERTAIN must always fall back to the legacy check.
_attr_awk='
function basename(t) { sub(/.*\//, "", t); return t }
function resolve(a,   r) {
  if (a == "") return (home != "" ? "CONF:" home : "UNCERTAIN")   # bare cd → HOME
  if (a == "-") return "UNCERTAIN"
  if (a ~ /^\$\{?HOME\}?(\/|$)/) {                                # $HOME_DIR etc. fall through to UNCERTAIN
    if (home == "") return "UNCERTAIN"
    r = a; sub(/^\$\{?HOME\}?/, "", r)
    return "CONF:" home r
  }
  if (a ~ /^\$/) return "UNCERTAIN"
  if (a ~ /^~(\/|$)/) { if (home == "") return "UNCERTAIN"; return "CONF:" home substr(a, 2) }
  if (a ~ /^~/) return "UNCERTAIN"                                # ~user is not our HOME
  if (a == ".." || a ~ /(\/|^)\.\.(\/|$)/ || a ~ /[$`]/) return "UNCERTAIN"
  if (a ~ /^\//) return "CONF:" a
  if (tentative ~ /^CONF:/) return "CONF:" substr(tentative, 6) "/" a
  return "UNCERTAIN"
}
function start_chain(bg) { tentative = committed; chain_has_cd = 0; chain_or = 0; bg_chain = bg }
function commit_chain() {
  if (chain_has_cd && !bg_chain) committed = "UNCERTAIN"   # a cd may or may not have run
  start_chain(0)
}
function finalize(close_reason,   i, k, nt, T, cmd, raw, attr, has_cdtok, j, t, dashc, pa, rc) {
  rc = redir_cd; redir_cd = 0
  if (nested) { print "UNCERTAIN"; seg = ""; pipe_adj = 0; seg_folded_cd = 0; return }
  pa = (pipe_adj || close_reason == "|" || close_reason == "&")   # subshell-executed segment
  # A cd split off by a redirect-& (2>&1) continues in this fragment: keep its || taint,
  # and it cannot stay folded when the fragment turns out to be a pipeline stage.
  seg_folded_cd = rc
  if (rc && pa) tentative = "UNCERTAIN"
  nt = split(seg, T, /[ \t]+/)
  # Env-var repo redirects (also via export/env) decide the repo elsewhere — sticky for the rest of the command.
  for (j = 1; j <= nt; j++) if (T[j] ~ /^GIT_(DIR|WORK_TREE|COMMON_DIR|NAMESPACE)=/) git_redirect = 1
  i = 1
  while (i <= nt && (T[i] == "" || T[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=/)) i++   # empties + env assignments
  if (i <= nt && T[i] == "!") i++
  raw = (i <= nt ? T[i] : "")
  cmd = basename(raw)
  k = i                                                           # cd counts only in command position
  while (k <= nt && T[k] ~ /^(!|if|then|do|else|elif|while|until|time|command|builtin)$/) k++
  has_cdtok = (k <= nt && T[k] ~ /^(cd|pushd|popd)$/)
  if (cmd == "eval") for (j = i + 1; j <= nt; j++) if (T[j] ~ /^(cd|pushd|popd)$/) has_cdtok = 1
  attr = ""
  if (raw == "cd" && !pa) {                 # literal token only: a pathed cd is an
    j = i + 1                                # external binary — it cannot fold
    while (j <= nt && T[j] ~ /^-/) j++                           # cd -L / -P flags
    t = (j <= nt ? T[j] : "")
    if (t == "--" && j + 1 <= nt) t = T[j + 1]
    tentative = (chain_or ? "UNCERTAIN" : resolve(t))
    chain_has_cd = 1
    seg_folded_cd = 1
  } else if (has_cdtok && !pa) {
    tentative = "UNCERTAIN"                                     # conditional-position cd
    chain_has_cd = 1
    if (cmd == "eval") attr = "UNCERTAIN"
  } else if (cmd ~ /^(bash|sh|zsh|dash|ssh|docker|podman|kubectl|su)$/) {
    attr = "UNCERTAIN"                                          # body re-parsed elsewhere
  } else if (cmd == "git") {
    dashc = ""
    j = i + 1
    while (j <= nt) {
      t = T[j]
      if (t ~ /^--(git-dir|work-tree|namespace)(=|$)/) { attr = "UNCERTAIN"; break }   # repo decided elsewhere
      if (t == "-C") { dashc = (j + 1 <= nt ? resolve(T[j + 1]) : "UNCERTAIN"); j += 2; continue }
      if (t ~ /^-C./) { dashc = resolve(substr(t, 3)); j++; continue }
      if (t == "-c" || t ~ /^--(config|config-env|exec-path)(=|$)/) {
        if (t ~ /=/ || t ~ /^-c./) j++; else j += 2
        continue
      }
      if (t ~ /^-/) { j++; continue }
      if (t == "push" || t == "reset") { if (dashc != "") attr = dashc }
      break
    }
  } else {
    # git behind a wrapper (sudo/env/timeout/xargs/…): its globals are not parsed here.
    for (j = i + 1; j <= nt; j++) if (basename(T[j]) == "git") { attr = "UNCERTAIN"; break }
  }
  print (git_redirect ? "UNCERTAIN" : (attr != "" ? attr : tentative))
  seg = ""; pipe_adj = 0
}
BEGIN {
  in_sq = 0; in_dq = 0; committed = "CONF:" base; tentative = committed
  chain_has_cd = 0; chain_or = 0; bg_chain = 0; pipe_adj = 0
  nested = 0; bt = 0; twin = 0; seg = ""; seg_folded_cd = 0; git_redirect = 0; redir_cd = 0
}
{
  line = $0; n = length(line)
  for (i = 1; i <= n; i++) {
    c = substr(line, i, 1)
    if (c == "\\" && !in_sq) { if (i < n) { seg = seg substr(line, i + 1, 1); i++ }; continue }
    if (c == "\x27" && !in_dq) { in_sq = !in_sq; continue }
    if (c == "\"" && !in_sq) { in_dq = !in_dq; continue }
    if (c == "[" || c == "]" || c == "{" || c == "}") continue
    if (c == "\t") c = " "
    if (!in_sq && !in_dq) {
      if (c == "(" ) { finalize("("); nested++; twin = 0; continue }
      if (c == ")") { finalize(")"); if (nested > 0) nested--; twin = 0; continue }
      if (c == "`") { finalize("`"); if (bt) { bt = 0; if (nested > 0) nested-- } else { bt = 1; nested++ }; twin = 0; continue }
      if (c == ";") { finalize(";"); commit_chain(); twin = 0; continue }
      if (c == "&" || c == "|") {
        # Redirection ampersand (2>&1, >&2, &>): not a background operator. Still finalize
        # for line parity with _segment_awk, but leave the chain state alone.
        if (c == "&" && !twin && (substr(line, i - 1, 1) ~ /[<>]/ || substr(line, i + 1, 1) == ">")) {
          finalize("redir"); redir_cd = seg_folded_cd; continue
        }
        if (twin) { finalize("twin"); twin = 0; continue }
        tw = (substr(line, i + 1, 1) == c)
        if (c == "|") finalize(tw ? "or" : "|")
        else finalize(tw ? "and" : "&")
        if (tw) {
          twin = 1
          if (c == "|") {
            chain_or = 1
            # A command right of || runs only when the left side FAILED — a cd that
            # just folded left of || must not keep its target for the chain tail.
            if (seg_folded_cd) tentative = "UNCERTAIN"
          }
        }
        else if (c == "&") start_chain(1)
        else pipe_adj = 1
        continue
      }
    }
    seg = seg c
  }
  if (in_sq || in_dq) { seg = seg " " }
  else { finalize("nl"); commit_chain(); twin = 0 }
}
END { if (seg != "") finalize("eof") }'

# Sets _branch/_target for one push/reset segment. Uncertain (or non-repo) targets check
# BOTH the base dir and the guard process cwd and keep whichever is protected, so the
# block set stays a superset of the legacy process-cwd check (docs/hooks.md §2).
_attributed_branch() {
  _branch=''; _target=''
  case "$1" in
    CONF:*) _target=${1#CONF:}
            _branch=$(git -C "$_target" rev-parse --abbrev-ref HEAD 2>/dev/null || true) ;;
  esac
  if [[ -z "$_branch" ]]; then
    _target=
    _branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    case "$_branch" in
      main|master|release/*) ;;
      *) _base_branch=$(git -C "$_base" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
         case "$_base_branch" in main|master|release/*) _branch=$_base_branch ;; esac ;;
    esac
  fi
}

# Classify each force-push segment independently so later `-f` values do not affect earlier
# non-force pushes. FD3 carries the attribution stream; an exhausted stream reads UNCERTAIN.
while IFS= read -r push_cmd; do
  IFS= read -r seg_attr <&3 || seg_attr='UNCERTAIN'
  push_norm=$(printf '%s' "$push_cmd" | tr '()' '  ' | tr '\t`' '  ' | tr -d "'\"[]{}\\\\")
  _toks=()
  read -ra _toks <<<"$push_norm"
  prefix_ok=1; prefix_args=0; found_git=0
  if (( ${#_toks[@]} )); then                 # bash 3.2 + set -u rejects empty "${arr[@]}"
  for _prefix in "${_toks[@]}"; do
    case "$_prefix" in
      git|*/git) found_git=1; break ;;
      [[:alpha:]_][[:alnum:]_]*=*) prefix_args=1 ;;
      # Transparent pass-through prefixes; additions require guard_cases() coverage.
      sudo|env|time|nice|nohup|command|exec|xargs|timeout|watch|ssh|bash|sh|zsh|dash|eval|rtk|\
      docker|podman|kubectl|su|setsid|stdbuf|flock|script|*/rtk|*/docker|*/podman|*/kubectl)
        prefix_args=1 ;;
      '!'|if|while|until|do|then) ;;
      -*) (( prefix_args )) || prefix_ok=0 ;;
      *) (( prefix_args )) || prefix_ok=0 ;;
    esac
  done
  fi
  # Keep the established fail-safe treatment of literal tab-prefixed git.
  [[ "$push_cmd" == *$'\t'* ]] && prefix_ok=1
  if (( found_git == 0 || prefix_ok == 0 )); then
    continue
  fi

  has_force=0; has_refspec=0; pushes_all_refs=0; seen_positional=0; consume_next=0
  seen_git=0; seen_push=0; global_value=0
  if (( ${#_toks[@]} )); then                 # guard: bash 3.2 + set -u errors on empty "${arr[@]}"
    for _t in "${_toks[@]}"; do
      if (( seen_push == 0 )); then
        if (( seen_git == 0 )); then
          [[ "$_t" == git || "$_t" == */git ]] && seen_git=1
          continue
        fi
        if (( global_value )); then
          global_value=0
          continue
        fi
        case "$_t" in
          push) seen_push=1 ;;
          -c|-C|--config|--config-env|--exec-path|--git-dir|--work-tree|--namespace)
            global_value=1 ;;
          --config=*|--config-env=*|--exec-path=*|--git-dir=*|--work-tree=*|--namespace=*|-c*|-C*) ;;
          -*) ;;
          *) ;;
        esac
        continue
      fi
      if (( consume_next )); then             # swallow an unrecognized flag's separate-word value
        case "$_t" in
          --force|-f) has_force=1 ;;
          --all) pushes_all_refs=1 ;;
          --mirror) has_force=1; pushes_all_refs=1 ;;
          -*) [[ "$_t" != --* && "$_t" == *f* ]] && has_force=1 ;;
        esac
        consume_next=0
        continue
      fi
      case "$_t" in
        --force|-f) has_force=1 ;;
        --all) pushes_all_refs=1 ;;
        --mirror) has_force=1; pushes_all_refs=1 ;;
        # Known BOOLEAN-only push flags — safe to skip outright. An
        # unrecognized `-*` flag is assumed to take a separate-word value and
        # that value is consumed too, so it cannot be a remote or refspec.
        --force-with-lease*|--force-if-includes|--tags|--follow-tags|--prune|--thin|--atomic|\
        --no-verify|--dry-run|--porcelain|-q|--quiet|-v|--verbose|--progress|--no-progress|\
        -u|--set-upstream|-d|--delete|--signed|--no-signed|-n) ;;
        --*=*) ;;                             # attached long-option value
        -*)
          if [[ "$_t" != --* && "$_t" == *f* ]]; then
            has_force=1                       # fail-safe short cluster containing -f
          elif [[ "$_t" == -[[:alnum:]][[:alnum:]]* ]]; then
            :                                 # attached short-option value
          else
            consume_next=1                   # unknown flag may take a separate-word value
          fi ;;
        *:*) has_refspec=1 ;;                 # src:dst refspec
        *) if (( seen_positional )); then has_refspec=1; else seen_positional=1; fi ;;  # 1st bareword = remote
      esac
    done
  fi
  if (( has_force == 0 )); then
    continue
  fi

  if (( pushes_all_refs )); then
    echo 'BLOCKED: force push of all refs may update protected branches' >&2
    exit 2
  fi

  if echo "$push_norm" | grep -Eq \
    '(^|[[:space:]]|:)(refs/heads/)?(main|master|release/[^[:space:]:]*)([[:space:]]|:|$)'; then
    echo 'BLOCKED: force push to protected branch (main/master/release/*)' >&2
    exit 2
  fi

  if (( has_refspec == 0 )); then             # relies on push.default / upstream
    _attributed_branch "$seg_attr"
    case "$_branch" in
      main|master|release/*)
        if [[ -n "$_target" && "$_target" != "$_base" ]]; then
          echo "BLOCKED: force push of current protected branch '$_branch' (implicit upstream, target $_target)" >&2
        else
          echo "BLOCKED: force push of current protected branch '$_branch' (implicit upstream)" >&2
        fi
        exit 2
        ;;
    esac
    if [[ -n "$_target" && "$_target" != "$_base" ]]; then
      _warn_reason="bash_guard: target repo resolved to $_target; protected-branch check ran there, not $_base"
    elif [[ -z "$_target" && "$seg_attr" != "CONF:$_base" ]]; then
      _warn_reason="bash_guard: could not resolve effective directory (unresolvable cd); protected-branch check ran against $_checked only"
    fi
  fi
done < <(printf '%s' "$_bj" | awk -v tab_mode=keep "$_segment_awk") 3< <(printf '%s' "$_bj" | awk -v base="$_base" -v home="${HOME:-}" "$_attr_awk")

case "$norm" in
*reset*--hard*)
  # Tokenized per-segment scan (git → global flags → reset → --hard) so `git -C <dir> reset --hard` matches.
  while IFS= read -r seg_cmd; do
    IFS= read -r seg_attr <&3 || seg_attr='UNCERTAIN'
    seg_norm=$(printf '%s' "$seg_cmd" | tr '()' '  ' | tr '\t`' '  ' | tr -d "'\"[]{}\\\\")
    read -ra _rt <<<"$seg_norm"
    _rs=0 _hit=0
    if (( ${#_rt[@]} )); then
      for _t in "${_rt[@]}"; do
        case $_rs in
          0) [[ "$_t" == git || "$_t" == */git ]] && _rs=1 ;;
          1) case "$_t" in
               -c|-C|--config|--config-env|--exec-path|--git-dir|--work-tree|--namespace) _rs=3 ;;
               --config=*|--config-env=*|--exec-path=*|--git-dir=*|--work-tree=*|--namespace=*|-c*|-C*) ;;
               -*) ;;
               reset) _rs=2 ;;
               *) break ;;
             esac ;;
          2) [[ "$_t" == --hard ]] && { _hit=1; break; } ;;
          3) _rs=1 ;;
        esac
      done
    fi
    (( _hit )) || continue
    _attributed_branch "$seg_attr"
    case "$_branch" in
      main|master|release/*)
        if [[ -n "$_target" && "$_target" != "$_base" ]]; then
          echo "BLOCKED: git reset --hard on protected branch '$_branch' (target $_target)" >&2
        else
          echo "BLOCKED: git reset --hard on protected branch '$_branch'" >&2
        fi
        exit 2
        ;;
    esac
    if [[ -n "$_target" && "$_target" != "$_base" ]]; then
      _warn_reason="bash_guard: target repo resolved to $_target; protected-branch check ran there, not $_base"
    elif [[ -z "$_target" && "$seg_attr" != "CONF:$_base" ]]; then
      _warn_reason="bash_guard: could not resolve effective directory (unresolvable cd); protected-branch check ran against $_checked only"
    fi
  done < <(printf '%s' "$_bj" | awk -v tab_mode=keep "$_segment_awk") 3< <(printf '%s' "$_bj" | awk -v base="$_base" -v home="${HOME:-}" "$_attr_awk")
  ;;
esac

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

if [[ -n "$_warn_reason" ]]; then
  jq -cn --arg msg "$_warn_reason" '{systemMessage:$msg}'   # no permissionDecision: "allow" would skip Claude Code's prompt
fi
exit 0
