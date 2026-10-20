#!/usr/bin/env bash
# PreToolUse:Bash guard — block destructive commands and short-circuit safe ones.
#
# Blocks:
#   - rm -rf against /, /*, ~, $HOME, /Users[/<user>], /home[/<user>]
#   - git push --force / -f to main/master/release/*; with no refspec, the current branch of the
#     repository -C / --git-dir names decides (else the payload's cwd); one that cannot be resolved,
#     or --work-tree without --git-dir, blocks
#   - a force push with a dynamic destination or flag (an unquoted brace group included), with no
#     refspec into a repository a GIT_DIR-like assignment or a dynamic -C/--git-dir/--work-tree
#     value selects, nesting too deep to scan, or a command over 64 KB that spells one literally or
#     through a brace group or substitution, on any branch. The exception: a word that is exactly
#     `$(git branch --show-current)` (or the rev-parse / symbolic-ref spelling) is the current
#     branch, so it blocks only on a protected one
#   - a push, `git reset --hard` or `pi` check whose awk or tr preprocessing fails: blocked, never skipped (an
#     environment without awk blocks every command, as a jq failure already does)
#   - git reset --hard on main/master/release/* only when it would lose data: uncommitted changes, or
#     commits no other branch, tag or remote keeps. The target is the repository named by -C /
#     --git-dir / --work-tree (else the payload's cwd, or the hook's own without one; a payload cwd
#     that no longer exists blocks); feature branches and a detached HEAD are never judged.
#     Anything unresolvable or dynamic fails closed: a missing repo or ref, a substitution in
#     the path or target, GIT_DIR-like assignments, -c core.worktree/core.bare, --recurse-submodules,
#     and an earlier step of the same command that may have changed the repository (run it as its own
#     command first). The exception is a plain `git branch <name>` (or `switch -c` /
#     `checkout -b`) at HEAD earlier in the same `&&` chain and repository: it keeps the
#     commits, so only the uncommitted and untracked checks apply, while no branch of that name
#     exists yet and nothing after the reset may change the repository. Quoted text such as
#     `echo 'git reset --hard'` is data and is not judged, but code assembled from data in a
#     command that mentions `reset ... --ha` (`| bash`, `eval`, `$x`, `bash -c "$x"`,
#     `source <(...)`) blocks on a protected branch, loss or not. A reset that is
#     nested too deep to scan, or sits in a command over 64 KB, blocks on any branch.
#   - a `pi` invocation carrying -p/--print in the same command segment (nested
#     non-interactive pi session — the bash escape hatch around the subagent
#     dispatcher's --exclude-tools recursion guard; see
#     docs/task-dispatch.md)
#
# Short-circuits (exit 0, no greps) for commands that contain none of "rm",
# "git", or "pi". This is the common case (ls, cat, echo, make, npm, …) and
# removes the per-call grep tax flagged in #233.
#
# Out of scope: ${HOME} brace-form; ANSI-C $'...' quoting; path normalization via .. traversal; compound cd (only the session cwd is known);
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
# Accepted gaps: function/coproc NAME bodies; unlisted wrappers; brace expansion in the rm and pi
# detectors (`rm -rf {/,}`); bash 3.2's mis-parsing of a heredoc body inside `$(` (an unmatched `)`
# or quote there ends the substitution early on /bin/bash 3.2) is out of scope, the guard models
# bash 4 and later.
# Also accepted, each because the text holds no value to judge (the cost is a push the guard
# does not see):
#   - a substitution is read as the force flag only as the first positional or beside a literal
#     protected ref: `git push origin $(echo --force)` and a substitution flag next to a
#     substitution destination (`git push $(echo --force) origin $(echo main)`) pass, because
#     blocking every computed destination would block ordinary pushes
#   - values that are never resolved: a heredoc assigned to a variable and run later
#     (`X="$(cat <<'EOT' ... EOT)"; eval "$X"`), parameter expansions (`B=main; git push -f origin
#     $B`, `${B:-main}`), and a subcommand spelled by a substitution (`git $(echo push) -f ...`)
#   - the current-branch query is assumed to run where the push does, so `cd other &&`, an earlier
#     `git checkout` or `switch` are not followed (the hook payload carries no cwd after a cd)
#   - a command word spelled by a brace group or substitution (`{git,} push -f origin main`)
#   - an odd quote inside a heredoc body desyncs the comment stripper, and a bare-delimiter
#     `cat <<EOF` heredoc inside `$(` is lexed as code, so a lone apostrophe in its text can hide a
#     later push (`git commit -m "$(cat <<EOF ... Don't ... EOF)" && git push -f origin main`):
#     both predate the push scan; the quoted-delimiter and top-level forms are handled
#   - a command with many `$(...)`: each costs an awk process (about 40 ms), so a few hundred can
#     outlast the hook timeout; the 64 KB cap bounds size, not time
# Over-blocks taken to stay fail-safe: a wildcard force push (`refs/tags/*`) counts as all refs; a
# non-force `git push "$(...)"` on a protected branch may be the force flag spelled by a
# substitution; a brace group after a protected ref (`git push origin main {a,b}`) may be the force
# flag; `ssh host echo "…git push -f…"` and other wrapper argument text is code; a `cat <<'EOT'`
# body inside a compound or nested substitution (`$(true; cat <<'EOT' ...)`) is scanned as code;
# over 64 KB, a `git ... push` carrying a brace group, `$` or a backtick blocks, and so does any
# command holding both a `pi` token and a `-p`/`--print` token (no segmenter runs).
#
# Reset-only gaps (the text scan cannot see these; the old whole-text grep caught some of them):
#   - the subcommand spelled through an expansion (`git ${S:-reset} --hard`); code assembled
#     from data is only caught by its `reset ... --ha` text (above). The push scan shares this.
#   - somewhere other than the session cwd: `cd x && git reset --hard`, `env -C x`, `docker exec`,
#     `ssh` (the sequenced-step rule still blocks the `cd` form on a protected cwd); GIT_* variables
#     in the hook's own environment; git aliases, including `-c alias.x=...`.
#   - state the verdict cannot credit or see: a fetch before the reset (judged against the refs
#     as they were); a switch to a remote-tracking name (`git checkout -b x origin/main`);
#     edits to an `--assume-unchanged` file; a later step deleting a branch the loss check
#     counted on (`git reset --hard X && git branch -D feature`, only `feature` holding them).
#   - over-blocks, on purpose: the dirty check is stat-based, so touched-but-unchanged files block
#     (run `git status` and retry); the subcommand is the first word after git's global options, but
#     an unknown option or an expansion before it, or a subcommand that runs the rest of its words
#     (`submodule foreach`, `bisect run`, `for-each-repo`), matches `reset` at any later position;
#     a bare `--exec-path` and `--config` (no-ops or errors in git) count as unknown options and
#     block; a leading expansion or substitution in a reset argument, a `~` in a -C path and an
#     unquoted `@{u}` (the lexer drops the braces) are blocked rather than guessed.
# The read-only git calls in the verdict never forward the user's `-c` values and switch off
# fsmonitor and clean/process filter drivers, because config can execute code before approval.
# The scan and the verdicts run as one job with a 3 s budget (SWE_WORKBENCH_GUARD_GIT_BUDGET lowers
# it, 1-3 s): a repository config that makes git hang (a FIFO include), or a command too long to
# scan in that time, blocks the command.
# --force-with-lease/--force-if-includes intentionally unblocked (#163); the push scan lexes quotes
# (quoted text is literal, substitutions are scanned); a remote literally
# named main/master over-blocks. The push-token scan trusts a small allowlist of known
# BOOLEAN-only push flags and defensively consumes the next token for any other `-*` flag
# (assumes it takes a separate-word value, e.g. `-o ci.skip`) so an unknown flag's value can never
# be miscounted as the remote/refspec (#501 senior-engineer consult); an unrecognized flag that
# actually takes NO value over-blocks by one token (fail-safe direction). Push and reset long
# options resolve by unique prefix as git's parse-options does (`--mirr`, `reset --h`); one git
# rejects as ambiguous (`--forc`, `--fo`) counts as such an unknown flag.
# Quotes are stripped before matching (same fail-safe direction as that over-block
# above), so a `pi -p` mention inside an unrelated quoted string (e.g. a commit message) can
# over-block too — accepted, not special-cased.

set -u

# Read once: .cwd is extracted from the same payload, but only after the fast gate.
IFS= read -r -d '' payload || true
if ! cmd=$(jq -r '.tool_input.command // ""' <<< "$payload"); then
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
MAX_EXACT_SCAN_CHARS=65536
_oversize=0
(( ${#cmd} > MAX_EXACT_SCAN_CHARS )) && _oversize=1

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

# Quote- and escape-aware shell segmenter for the pi detector (the push and reset scans share the
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

# Lexer shared by the push and reset scans: redirects are syntax; empty quoted words and live
# substitutions stay in their word.
# shellcheck disable=SC2016 # AWK source is intentionally a single-quoted literal.
_seg_token_awk='
  function emit_word() {
    if (!word_started) return
    if (redirect_target) { if (here_string) print "HERE\t" word; redirect_target = 0; here_string = 0 }
    else { print "WORD\t" ((cur_branch && word == dyn) ? cur : word); wcount++ }
    word = ""; word_started = 0; cur_branch = 0
  }
  function finish_subst() {
    print "NEST\t" subtext
    # a word that is exactly one current-branch query is the current branch, not an unknown value
    cur_branch = (word == "" && subtext ~ /^[ \t]*(rtk[ \t]+)?git[ \t]+(branch[ \t]+--show-current|rev-parse[ \t]+--abbrev-ref[ \t]+HEAD|symbolic-ref[ \t]+--short[ \t]+HEAD)([ \t]+2>[ \t]*\/dev\/null)?[ \t]*$/)
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
  # End index of the unquoted brace group opening at line[p] when it is expansion (a comma or `..`
  # at its top level, no unquoted whitespace or operator inside), else 0. The look-ahead is
  # bounded so a run of `{` stays linear; a group still open at the bound that already holds a
  # comma counts as expansion.
  function brace_group_end(p, n,   d, k, ch, q, expands, lim) {
    d = 0; q = ""; expands = 0; lim = (p + 256 < n) ? p + 256 : n
    for (k = p; k <= lim; k++) {
      ch = substr(line, k, 1)
      if (q != "") {
        if (ch == "\\" && q == "\"") k++
        else if (ch == q) q = ""
        continue
      }
      if (ch == "\\") { k++; continue }
      if (ch == "\047" || ch == "\"") { q = ch; continue }
      if (ch ~ /[ \t\n;|&<>()`]/) return 0
      if (ch == "{") d++
      else if (ch == "}") { d--; if (d == 0) return expands ? k : 0 }
      else if (d == 1 && ch == ",") expands = 1
      else if (d == 1 && ch == "." && substr(line, k + 1, 1) == ".") expands = 1
    }
    return (expands && lim < n) ? lim : 0
  }
  # SEP carries the separator kind a consumer needs: AND for `&&`, LIST for `;` and a newline
  # (they start a new list), PIPE for a single `|` or `|&`; any other separator is a bare SEP
  function emit_separator(kind) {
    emit_word()
    redirect_target = 0; here_string = 0; wcount = 0
    print (kind == "" ? "SEP" : "SEP\t" kind)
  }
  function begin_redirect() {
    if (word_started && word ~ /^[0-9]*$/) {
      word = ""; word_started = 0
    } else emit_word()
    redirect_target = 1
    # the segment writes or reads a file: it is not a plain git call
    print "REDIR"
  }
  BEGIN { in_sq = 0; in_dq = 0; escaped = 0; word = ""; word_started = 0; cur_branch = 0; wcount = 0; arith = 0; pe = 0; redirect_target = 0; here_string = 0; hd_nl = 0; hd_to = 0 }
  { buf = (NR == 1) ? $0 : buf "\n" $0 }
  END {
    line = buf; gsub(/\001/, "\n", line); n = length(line)
    for (i = 1; i <= n; i++) {
      c = substr(line, i, 1)
      # an unquoted heredoc body: quotes and operators are text, only expansions are live
      if (hdmode) {
        if (c == "\\") { i++; continue }
        if (c != "$" && c != "`") continue
      }
      if (hd_nl > 0 && i > hd_nl) hd_nl = 0
      if (c == "\n") {
        escaped = 0
        if (in_sq || in_dq) { word = word "\001"; word_started = 1 } else {
          emit_separator("LIST")
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
        # PSUB: the segment holds a process substitution
        if (substr(line, i + 1, 1) == "(") { emit_word(); print "PSUB"; continue }
        if (c == "<" && substr(line, i, 3) == "<<<") here_string = 1
        if (c == "<" && substr(line, i, 2) == "<<" && substr(line, i, 3) != "<<<" && hd_nl == 0 && arith == 0 && pe == 0) {
          # a quoted-delimiter heredoc whose start line ends there (a pipe or && would let the
          # body reach another consumer) is data: skip it so its quotes cannot desync the lexer
          hj = i + 2; hstrip = 0
          if (substr(line, hj, 1) == "-") { hstrip = 1; hj++ }
          while (substr(line, hj, 1) ~ /[ \t]/) hj++
          hq = substr(line, hj, 1); hid = ""; hend = 0; hunq = 0
          if ((hq == "\047" || hq == "\"") && match(substr(line, hj + 1), /^[A-Za-z_][A-Za-z0-9_]*/)) {
            hid = substr(line, hj + 1, RLENGTH)
            hend = hj + 1 + RLENGTH
            if (substr(line, hend, 1) != hq) hid = ""; else hend++
          } else if (hq == "\\" && match(substr(line, hj + 1), /^[A-Za-z_][A-Za-z0-9_]*/)) {
            hid = substr(line, hj + 1, RLENGTH)
            hend = hj + 1 + RLENGTH
          } else if (hq ~ /[A-Za-z_]/ && match(substr(line, hj), /^[A-Za-z_][A-Za-z0-9_]*/)) {
            # a bare delimiter leaves the body expanding substitutions: UHERE tells the caller to look for them
            hid = substr(line, hj, RLENGTH)
            hend = hj + RLENGTH
            hunq = 1
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
                print (hunq ? "UHERE" : "HERE") "\t" hb
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
        sub_w = ""; sub_wcmd = 0; sub_case[1] = 0
        i += 2
        for (; i <= n; i++) {
          sc = substr(line, i, 1)
          if (sc == "\n") {
            sc = ";"
            # a quoted-delimiter `cat <<` heredoc body is skipped wherever the command sits, so its quotes
            # cannot desync the lexer; nothing may follow the delimiter (a pipe makes it code) and `cat <<`
            # is real syntax at command position, not text inside a quoted word. Only when `cat` is the
            # whole outermost substitution is the body data of its word; in a compound or nested one the
            # output may run (`$(echo x; $(cat <<'EOT' ...))`), so the body is scanned as code.
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
                  if (sub_depth != 1 || unquoted(subtext) !~ /^[ \t]*cat[ \t]+<<-?[ \t]*Q[ \t]*$/) print "NEST\t" hbody
                  else if (redirect_target && here_string) print "HERE\t" hbody
                  else print "SUBHERE\t" (redirect_target ? -1 : wcount) ":" hbody
                  i = pos + length(ltxt) - 1
                }
              }
            }
          }
          # `case` and `esac` at command position: inside a case, `)` ends a pattern
          if (!sub_sq && !sub_dq && sc ~ /[A-Za-z0-9_]/) {
            if (sub_w == "") sub_wcmd = (subtext ~ /(^|[;&|({])[ \t]*$/ || subtext ~ /(^|[ \t;&|({])(then|do|else|elif|if|while|until|time|!)[ \t]+$/)
            sub_w = sub_w sc
          } else {
            if (sub_wcmd) {
              # `case` opens a case only before a blank (`case=1` and `case-x` are not)
              if (sub_w == "case" && sc ~ /[ \t]/) sub_case[sub_depth]++
              else if (sub_w == "esac" && sub_case[sub_depth] > 0) sub_case[sub_depth]--
            }
            sub_w = ""; sub_wcmd = 0
          }
          if (sc == "\\" && !sub_sq) {
            subtext = subtext sc
            if (i < n) { i++; subtext = subtext substr(line, i, 1) }
            continue
          }
          if (sc == "\047" && !sub_dq) { sub_sq = !sub_sq; subtext = subtext sc; continue }
          if (sc == "\"" && !sub_sq) { sub_dq = !sub_dq; subtext = subtext sc; continue }
          if (!sub_sq && !sub_dq && sc == "(") { sub_depth++; sub_case[sub_depth] = 0; subtext = subtext sc; continue }
          if (!sub_sq && !sub_dq && sc == ")" && sub_case[sub_depth] > 0) { subtext = subtext sc; continue }
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
            # inside backticks `\\`, `\`` and `\$` lose one backslash; anything else keeps it
            i++; bq = substr(line, i, 1)
            if (bq == "\\" || bq == "`" || bq == "$") subtext = subtext bq
            else subtext = subtext sc bq
            continue
          }
          if (sc == "`") break
          subtext = subtext sc
        }
        finish_subst()
        continue
      }
      # `<<` is a shift, not a heredoc, inside (( )) and ${ }
      if (c == "(") { if (arith > 0 || substr(line, i + 1, 1) == "(") arith++ }
      else if (c == ")" && arith > 0) arith--
      if (c == "&" && substr(line, i + 1, 1) == "&") {
        emit_separator("AND")
        i++
        # a newline after `&&` continues the list (a heredoc body never starts here)
        while (i + 1 <= n && i + 1 != hd_nl && substr(line, i + 1, 1) ~ /[ \n]/) i++
        continue
      }
      if (c == "|") {
        # `||` is one list separator; `|&` pipes stderr too
        nc = substr(line, i + 1, 1)
        if (nc == "|" || nc == "&") i++
        emit_separator(nc == "|" ? "" : "PIPE")
        continue
      }
      if (c ~ /[;&()]/) {
        emit_separator(c == ";" ? "LIST" : "")
        continue
      }
      if (c == "{" && substr(word, length(word), 1) == "$") pe++
      else if (c == "}" && pe > 0) pe--
      if (c == "{" && substr(word, length(word), 1) != "$") {
        be = brace_group_end(i, n)
        if (be > 0) { word = word dyn; word_started = 1; i = be; continue }
      }
      if (c == "[" || c == "]" || c == "{" || c == "}") continue
      word = word c; word_started = 1
    }
    emit_separator()
    print "EOS"
  }
'

# The active segment is held in globals because Bash 3.2 has no namerefs.
# `scan_git_text` resets them at every lexical separator.
_seg_tokens=()
_seg_here=()
_seg_subs=()
# `cat <<'EOT'` heredocs inside `$(...)`: the word index each belongs to, and its body.
_seg_subhere_idx=()
_seg_subhere_body=()
_seg_saw_tab=0
# Set when the segment redirects its input or output.
_seg_redir=0
_DYNAMIC_TOKEN=__SWB_DYNAMIC_SUBSTITUTION__
# Stands for a word that is exactly a query for the current branch name.
_CURRENT_BRANCH_TOKEN=__SWB_CURRENT_BRANCH__
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
    # an expansion or substitution in this slot can spell a global option
    '$'*|"$_DYNAMIC_TOKEN"*) return 0 ;;
    add|am|annotate|apply|archive|bisect|blame|branch|bundle|cat-file|checkout|cherry|cherry-pick|\
    clean|clone|commit|config|credential|describe|diff|difftool|fast-export|fast-import|fetch|\
    filter-branch|for-each-ref|for-each-repo|format-patch|fsck|gc|grep|hash-object|help|init|\
    log|ls-files|ls-remote|ls-tree|maintenance|merge|mergetool|mv|name-rev|notes|pull|push|\
    range-diff|rebase|reflog|remote|repack|replace|request-pull|reset|restore|rev-list|rev-parse|\
    revert|rm|send-email|shortlog|show|show-branch|sparse-checkout|stash|status|submodule|svn|\
    switch|symbolic-ref|tag|update-ref|var|version|worktree) return 0 ;;
  esac
  return 1
}

# A push of the current branch ($1 is CHECK_CURRENT, or CHECK_CURRENT_MAYBE when a substitution
# may spell the force flag): the branch of the repository -C/--git-dir/--work-tree selects decides,
# so the record carries them, joined by \x1f, for the verdict. A repository the text does not spell
# (a GIT_DIR-like assignment, an expansion or substitution in a value) cannot be read, and a
# control character would corrupt the record.
_emit_current_check() {
  local _c _joined="" _sep=$'\x1f'
  if (( _git_env_ctx || _git_ctx_dynamic )); then
    printf 'BLOCK\tcontext-destination\n'
    return
  fi
  for _c in ${_git_ctx[@]+"${_git_ctx[@]}"}; do
    if [[ "$_c" == *[[:cntrl:]]* || "$_c" == *'$'* || "$_c" == *"$_CURRENT_BRANCH_TOKEN"* ]]; then
      printf 'BLOCK\tcontext-destination\n'
      return
    fi
    _joined="$_joined${_joined:+$_sep}$_c"
  done
  printf '%s\t%s\n' "$1" "$_joined"
}

_is_shell_interpreter() {
  case "$1" in bash|sh|zsh|dash|ksh|fish|su|eval|source|.) return 0 ;; esac
  return 1
}

# Locates the `git` command word of the active segment and walks its global options up to the
# subcommand, the first word that is no option nor an option's value. Globals (Bash 3.2 has no
# namerefs): _git_index (the `git` word), _git_sub_index (the subcommand when it is $1, -1
# otherwise), _git_ctx (-C/--git-dir/--work-tree as separate words, original order so
# `-C a -C b` compounds), _git_has_context (`-C ''` is a no-op), _git_ctx_dynamic,
# _git_cfg_risky (-c/--config-env on core.worktree/core.bare), _git_env_ctx (a GIT_DIR-like
# assignment before `git`). Returns 1 when the segment is not a git command.
_parse_git_invocation() {
  local _want=$1 _prefix _base _t _name
  local _i=0 _prefix_ok=1 _prefix_args=$_NESTED_WRAPPER_BODY _found_git=0
  local _global_value=0 _context_value=0 _config_value=0 _ctx_flag="" _any_position=0
  _git_index=-1; _git_sub_index=-1; _git_ctx=(); _git_has_context=0; _git_subcmd=""; _git_subcmd_index=-1
  _git_ctx_dynamic=0; _git_cfg_risky=0; _git_env_ctx=0; _git_has_cfg=0; _git_via_runner=0

  (( ${#_seg_tokens[@]} )) || return 1
  for _prefix in "${_seg_tokens[@]}"; do
    # an assignment is judged on the raw word: stripping a path first would turn `X=/a/b` into `b`
    if [[ "$_prefix" == [[:alpha:]_]=* || "$_prefix" == [[:alpha:]_][[:alnum:]_]*=* ]]; then
      _prefix_args=1
      _name=${_prefix%%=*}
      case "$_name" in
        GIT_CONFIG_NOSYSTEM) ;;
        GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM) [[ "${_prefix#*=}" == /dev/null ]] || _git_env_ctx=1 ;;
        GIT_DIR|GIT_WORK_TREE|GIT_INDEX_FILE|GIT_COMMON_DIR|GIT_CONFIG*) _git_env_ctx=1 ;;
      esac
      _i=$((_i + 1))
      continue
    fi
    if (( ${#_prefix} > 255 )); then _base=$_prefix; else _base=${_prefix##*/}; fi
    [[ "$_base" == *"$_DYNAMIC_TOKEN"?* ]] && _base=${_base##*"$_DYNAMIC_TOKEN"}
    case "$_base" in
      git)
        if _is_git_continuation "${_seg_tokens[_i + 1]-}"; then _found_git=1; break; fi
        (( _prefix_args )) || _prefix_ok=0 ;;
      '!'|if|while|until|do|then|else|elif|coproc) ;;
      "$_DYNAMIC_TOKEN"|"$_CURRENT_BRANCH_TOKEN") ;;
      -exec|-execdir|-ok|-okdir) _prefix_ok=1; _prefix_args=0 ;;
      *)
        if _is_wrapper_prefix "$_base"; then
          _prefix_args=1
        else
          (( _prefix_args )) || _prefix_ok=0
        fi
        # arguments that come from stdin or a file are not in the text (find's `{}` is a path)
        case "$_base" in xargs|parallel) _git_via_runner=1 ;; esac ;;
    esac
    _i=$((_i + 1))
  done
  (( _seg_saw_tab )) && _prefix_ok=1
  (( _found_git && _prefix_ok )) || return 1
  _git_index=$_i

  for ((_i = _git_index + 1; _i < ${#_seg_tokens[@]}; _i++)); do
    _t=${_seg_tokens[_i]}
    if (( _global_value )); then
      if (( _context_value )); then
        if (( ${#_t} )); then _git_has_context=1; _git_ctx+=("$_ctx_flag" "$_t"); fi
        [[ "$_t" == *"$_DYNAMIC_TOKEN"* ]] && _git_ctx_dynamic=1
      elif (( _config_value )); then
        _note_config_key "$_t"
      fi
      _global_value=0; _context_value=0; _config_value=0
      continue
    fi
    if (( ! _any_position )); then
      # A word the scan cannot place keeps the old match at any position: an unknown option may
      # take the next word as its value, and an expansion may spell options, so the subcommand is
      # unknown and a later reset or push must still be judged.
      case "$_t" in
        -c|-C|--config-env|--git-dir|--work-tree|--namespace|--super-prefix|--attr-source|\
        --shallow-file|-c?*|-C?*|--config-env=*|--git-dir=*|--work-tree=*|--namespace=*|\
        --super-prefix=*|--attr-source=*|--shallow-file=*|--exec-path=*|-p|--paginate|-P|\
        --no-pager|--bare|--no-replace-objects|--no-lazy-fetch|--no-optional-locks|--no-advice|\
        --literal-pathspecs|--glob-pathspecs|--noglob-pathspecs|--icase-pathspecs) ;;
        # a bare --exec-path prints and exits and --config is no git option: neither takes a value
        -*|*'$'*|*"$_DYNAMIC_TOKEN"*|*"$_CURRENT_BRANCH_TOKEN"*) _any_position=1 ;;
        *)
          # the first word that is no option nor an option's value names the subcommand
          _git_subcmd=$_t; _git_subcmd_index=$_i
          [[ -n "$_want" && "$_t" == "$_want" ]] && _git_sub_index=$_i
          case "$_t" in
            # these run the rest of their words as a command (`submodule foreach git reset
            # --hard`, `bisect run ...`, `for-each-repo --config=k reset --hard`): any position
            submodule|bisect|for-each-repo) _any_position=1 ;;
            *) break ;;
          esac ;;
      esac
    fi
    if (( _any_position )); then
      if [[ -n "$_want" && "$_t" == "$_want" ]]; then _git_sub_index=$_i; break; fi
      if [[ -z "$_git_subcmd" && "$_t" != -* ]]; then _git_subcmd=$_t; _git_subcmd_index=$_i; fi
    fi
    # a word led by a parameter expansion, or a flag holding one, can spell any option
    if [[ "$_t" == *'$'* && ( "$_t" == '$'* || "$_t" == -* ) ]]; then _git_ctx_dynamic=1; fi
    case "$_t" in
      -c|--config-env) _global_value=1; _config_value=1; _git_has_cfg=1 ;;
      --namespace|--super-prefix|--attr-source|--shallow-file) _global_value=1 ;;
      -C|--git-dir|--work-tree) _global_value=1; _context_value=1; _ctx_flag=$_t ;;
      --git-dir=*|--work-tree=*)
        _git_has_context=1; _git_ctx+=("${_t%%=*}" "${_t#*=}")
        [[ "$_t" == *"$_DYNAMIC_TOKEN"* ]] && _git_ctx_dynamic=1 ;;
      -C?*)
        _git_has_context=1; _git_ctx+=(-C "${_t#-C}")
        [[ "$_t" == *"$_DYNAMIC_TOKEN"* ]] && _git_ctx_dynamic=1 ;;
      --config-env=*) _git_has_cfg=1; _note_config_key "${_t#*=}" ;;
      -c?*) _git_has_cfg=1; _note_config_key "${_t#-c}" ;;
      *) ;;
    esac
  done
  return 0
}

# core.worktree / core.bare redirect which tree a command operates on; keys are case-insensitive.
_note_config_key() {
  local _key=${1%%=*}
  # a key spelled through an expansion could be either
  [[ "$_key" == *'$'* ]] && _git_cfg_risky=1
  case "$_key" in
    [Cc][Oo][Rr][Ee].[Ww][Oo][Rr][Kk][Tt][Rr][Ee][Ee]|[Cc][Oo][Rr][Ee].[Bb][Aa][Rr][Ee]) _git_cfg_risky=1 ;;
  esac
}

# The long options of `git push` and `git reset`, as `git push -h` / `git reset -h` list them
# (git 2.54-2.56), each spelled positively. A `--no-` word matches none of them and keeps its own
# handling: a negation takes no value and turns on neither force, mirror, all, hard nor submodule
# recursion. `--help` is left out because git takes it only spelled in full (`reset --h` is --hard).
_PUSH_LONG_OPTS=(--verbose --quiet --repo --all --branches --mirror --delete --tags --dry-run
  --porcelain --force --force-with-lease --force-if-includes --recurse-submodules --thin
  --receive-pack --exec --set-upstream --progress --prune --verify --follow-tags --signed
  --atomic --push-option --ipv4 --ipv6)
_RESET_LONG_OPTS=(--quiet --refresh --mixed --soft --hard --merge --keep --recurse-submodules
  --patch --auto-advance --unified --inter-hunk-context --intent-to-add --pathspec-from-file
  --pathspec-file-nul)

# Sets _long_opt to the candidate a long option names, as git's parse-options resolves it: an
# exact spelling wins, else the one candidate the word abbreviates; empty when it abbreviates
# several (git rejects it) or none, and the caller treats the word as unknown. It sets a variable
# rather than printing so the per-word scan forks nothing.
_long_opt_match() {
  local _w=$1 _c _hit="" _hits=0
  shift
  _long_opt=""
  for _c in "$@"; do
    if [[ "$_c" == "$_w" ]]; then _long_opt=$_c; return 0; fi
    if [[ "$_c" == "$_w"* ]]; then _hit=$_c; _hits=$((_hits + 1)); fi
  done
  if (( _hits == 1 )); then _long_opt=$_hit; fi
  return 0
}

# Sets _long_word to the word with its long option name (the part before `=`) spelled in full
# among the candidates; a word that resolves to none is kept as it is.
_long_word_canon() {
  local _w=$1 _name=${1%%=*}
  shift
  _long_word=$_w
  [[ "$_w" == --?* ]] || return 0
  _long_opt_match "$_name" "$@"
  if [[ -n "$_long_opt" ]]; then _long_word=$_long_opt${_w:${#_name}}; fi
  return 0
}

_classify_force_push_segment() {
  local _t push_text
  local _i _has_force=0 _has_refspec=0 _pushes_all_refs=0 _seen_positional=0 _has_dynamic=0 _has_context=0
  local _consume_next=0 _dynamic_flag_candidate=0
  local _consume_flag="" _glued_flag_candidate=0 _skip_tok=0 _tail=""
  local _positional_count=0 _first_positional_dynamic=0 _has_colon_refspec=0
  local _flag_cluster_re='^[A-Za-z]*f[A-Za-z]*$'
  local _protected_ref_re='(^|[[:space:]:+])(refs/heads/)?(main|master|release/[^[:space:]:]*)([[:space:]]|:|$)'

  _parse_git_invocation push || return
  (( _git_sub_index >= 0 )) || return
  _has_context=$_git_has_context

  for ((_i = _git_sub_index + 1; _i < ${#_seg_tokens[@]}; _i++)); do
    _t=${_seg_tokens[_i]}
    if (( _consume_next )); then
      _long_word_canon "$_t" "${_PUSH_LONG_OPTS[@]}"
      case "$_long_word" in
        --force|-f) _has_force=1 ;;
        --all|--branches) _pushes_all_refs=1 ;;
        --mirror) _has_force=1; _pushes_all_refs=1 ;;
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
    if [[ "$_t" == "$_CURRENT_BRANCH_TOKEN" ]]; then
      # `HEAD` here; the query runs in this directory, so it names the pushed branch only
      # when no other repository was selected
      (( _has_context )) && _has_dynamic=1
      _t=HEAD
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
    # git accepts any unambiguous prefix of a long option (`--mirr`, `--rep`); an ambiguous one
    # (`--forc`, `--fo`) is rejected by git and stays an unknown flag here
    _long_word_canon "$_t" "${_PUSH_LONG_OPTS[@]}"
    _t=$_long_word
    case "$_t" in
      --force|-f) _has_force=1 ;;
      --all|--branches) _pushes_all_refs=1 ;;
      --mirror) _has_force=1; _pushes_all_refs=1 ;;
      --force-with-lease|--force-if-includes|--tags|--follow-tags|--prune|--thin|--atomic|\
      --dry-run|--porcelain|-q|--quiet|-v|--verbose|--progress|-u|--set-upstream|-d|--delete|\
      --signed|-n|--verify|--no-*|-4|-6|--ipv4|--ipv6|--) ;;
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
  push_text=$(printf ' %s' "${_seg_tokens[@]}")
  # A substitution-led word that can finish a force flag counts next to a literal protected ref;
  # a glued one with no refspec checks the current branch (a bare one is a normal push).
  if (( ! _has_force && _dynamic_flag_candidate )); then
    if printf '%s\n' "$push_text" | grep -Eq "$_protected_ref_re"; then
      _has_force=1
    elif (( _glued_flag_candidate && ! _has_refspec )); then
      _emit_current_check CHECK_CURRENT_MAYBE
      return
    fi
  fi
  # A bare substitution first may itself be the force flag; with the destination implicit
  # (at most one literal positional after it) only the current branch is at stake.
  if (( ! _has_force && _first_positional_dynamic && _positional_count <= 2 && ! _has_colon_refspec )); then
    _emit_current_check CHECK_CURRENT_MAYBE
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
  if printf '%s\n' "$push_text" | grep -Eq "$_protected_ref_re"; then
    printf 'BLOCK\tprotected-ref\n'
    return
  fi
  (( _has_refspec )) || _emit_current_check CHECK_CURRENT
}

# Set once any earlier segment of the scan may have changed the repository. It is never reset, so
# a mutation inside a nested scan still counts for a reset that follows.
_git_prior_mutation=0
# Set when an earlier segment may have switched to a protected branch, so the branch read at hook
# time is not the one the reset will run on.
_git_prior_switch=0
# Branches created at HEAD earlier in the current `&&` chain of the top-level text, each with
# the context it ran in (joined by \x1f). They are not a mutation: a reset later in the same
# chain and context has its commits kept by them (see _credit_branch_segment).
_credit_names=()
_credit_ctx=()
# CHECK_RESET records emitted with credits; a mutation after one emits POST_MUTATION.
_credited_resets=0

# A segment that is exactly `git [ctx] branch [-q] <name> [HEAD]`, `git [ctx] switch [-q] -c
# <name> [HEAD]` or `git [ctx] checkout [-q] -b <name> [HEAD]`, at the top level and
# preceded only by `&&` in its list, records a credit instead of a mutation: the new branch
# sits at HEAD. Anything the scan cannot read plainly (a prefix word, -c, a redirect, a
# substitution, a name that is not literal) is no credit. Returns 1 when the segment is not one.
_credit_branch_segment() {
  local _i _n=${#_seg_tokens[@]} _name _c _ctxj="" _sep=$'\x1f'
  (( _scan_depth == 0 && ! _NESTED_WRAPPER_BODY && _chain_and )) || return 1
  (( ! _seg_saw_tab && ! _seg_redir && ! ${#_seg_subs[@]} )) || return 1
  (( ! ${#_seg_here[@]} && ! ${#_seg_subhere_body[@]} )) || return 1
  _parse_git_invocation "" || return 1
  (( _git_index == 0 && _git_subcmd_index > 0 )) || return 1
  (( ! _git_has_cfg && ! _git_env_ctx && ! _git_via_runner )) || return 1
  (( ! _git_ctx_dynamic )) || return 1
  # only -C/--git-dir/--work-tree between `git` and the subcommand
  for ((_i = _git_index + 1; _i < _git_subcmd_index; _i++)); do
    case "${_seg_tokens[_i]}" in
      -C|--git-dir|--work-tree) _i=$((_i + 1)) ;;
      -C?*|--git-dir=*|--work-tree=*) ;;
      *) return 1 ;;
    esac
  done
  for _c in ${_git_ctx[@]+"${_git_ctx[@]}"}; do
    [[ "$_c" == *[[:cntrl:]]* || "$_c" == *'$'* ]] && return 1
    [[ "$_c" == *"$_CURRENT_BRANCH_TOKEN"* ]] && return 1
    _ctxj="$_ctxj${_ctxj:+$_sep}$_c"
  done
  _i=$((_git_subcmd_index + 1))
  case "${_seg_tokens[_i]-}" in -q|--quiet) _i=$((_i + 1)) ;; esac
  case "$_git_subcmd" in
    branch) ;;
    switch) [[ "${_seg_tokens[_i]-}" == -c ]] || return 1; _i=$((_i + 1)) ;;
    checkout) [[ "${_seg_tokens[_i]-}" == -b ]] || return 1; _i=$((_i + 1)) ;;
    *) return 1 ;;
  esac
  _name=${_seg_tokens[_i]-}
  _i=$((_i + 1))
  # a literal name: no expansion, glob, quote residue or control character can hide in it
  # (a class, not a range: a range follows the locale's collation order)
  [[ -n "$_name" && "$_name" != -* && "$_name" != HEAD ]] || return 1
  [[ "$_name" != *[![:alnum:]._/-]* ]] || return 1
  [[ "$_name" != *"$_DYNAMIC_TOKEN"* && "$_name" != *"$_CURRENT_BRANCH_TOKEN"* ]] \
    || return 1
  if (( _i < _n )); then
    [[ "${_seg_tokens[_i]}" == HEAD ]] || return 1
    _i=$((_i + 1))
  fi
  (( _i == _n )) || return 1
  _credit_names+=("$_name")
  _credit_ctx+=("$_ctxj")
  return 0
}

_git_switch_token_risky() {
  case "$1" in
    main|master|release/*|refs/heads/main|refs/heads/master|refs/heads/release/*|-|@*) return 0 ;;
    *'$'*|*"$_DYNAMIC_TOKEN"*) return 0 ;;
  esac
  return 1
}

# Scanner half of the hard-reset check (no I/O): BLOCK for input that cannot be resolved, or
# CHECK_RESET <seq> <submodules> <dynamic-target> <target> C<credited names joined by \x1f>
# <context joined by \x1f> for _reset_verdict to judge against the real repository.
_classify_reset_segment() {
  local _i _t _hard=0 _mode_flag=0 _maybe=0 _target="" _have_target=0 _submod=0 _dyn=0 _eoo=0
  local _joined="" _c _n=0 _sep=$'\x1f' _has_gd=0 _has_wt=0 _seqv=$_git_prior_mutation
  local _cred=""
  (( _git_prior_switch )) && _seqv=2

  _parse_git_invocation reset || return
  (( _git_sub_index >= 0 )) || return
  for ((_i = _git_sub_index + 1; _i < ${#_seg_tokens[@]}; _i++)); do
    _t=${_seg_tokens[_i]}
    # after --end-of-options the next word is the target, even when it opens with a dash
    if (( _eoo )); then
      _eoo=0
      if (( ! _have_target )); then _have_target=1; _target=$_t; fi
      [[ "$_t" == -* ]] && { printf 'BLOCK\treset-unsafe-arg\n'; return; }
      continue
    fi
    [[ "$_t" == -- || "$_t" == ';' ]] && break
    if [[ "$_t" == --end-of-options ]]; then _eoo=1; continue; fi
    # a word that opens with a substitution or expansion (or is a flag holding one) may spell
    # the hard flag
    if [[ ( "$_t" == *"$_DYNAMIC_TOKEN"* || "$_t" == *'$'* ) && ( "$_t" == "$_DYNAMIC_TOKEN"* || "$_t" == '$'* || "$_t" == -* ) ]]; then
      _maybe=1
      _mode_flag=0  # git applies the last mode flag, so an earlier --soft does not cover this word
    fi
    if [[ "$_t" == -* ]]; then
      # git accepts any unique prefix of a long option: `--h` is --hard, `--rec` is
      # --recurse-submodules (which takes an optional value); the mode flags take none
      _long_word_canon "$_t" "${_RESET_LONG_OPTS[@]}"
      case "$_long_word" in
        --soft|--mixed|--keep|--merge) _mode_flag=1 ;;
        --hard) _hard=1 ;;
        --recurse-submodules|--recurse-submodules=*) _submod=1 ;;
      esac
      continue
    fi
    if (( ! _have_target )); then _have_target=1; _target=$_t; fi
  done
  (( _hard )) || (( _maybe && ! _mode_flag )) || return

  if (( _git_env_ctx )); then printf 'BLOCK\treset-env\n'; return; fi
  if (( _git_cfg_risky )); then printf 'BLOCK\treset-config\n'; return; fi
  if (( _git_ctx_dynamic )); then printf 'BLOCK\treset-dynamic-context\n'; return; fi
  (( _have_target )) || _target=HEAD
  # a target read from stdin, a file or `{}` is not in the text either
  if [[ "$_target" == *"$_DYNAMIC_TOKEN"* || "$_target" == *"$_CURRENT_BRANCH_TOKEN"* || "$_target" == *'$'* || $_git_via_runner == 1 \
        || ( $_maybe == 1 && $_hard == 0 ) ]]; then
    _dyn=1
    _target=HEAD
  fi
  # --work-tree alone keeps the repository of the cwd but resets another tree's files
  for _c in ${_git_ctx[@]+"${_git_ctx[@]}"}; do
    case "$_c" in --git-dir) _has_gd=1 ;; --work-tree) _has_wt=1 ;; esac
  done
  if (( _has_wt && ! _has_gd )); then printf 'BLOCK\treset-work-tree\n'; return; fi
  # a control character would corrupt the record below; a leading dash would read as a git option
  for _c in ${_git_ctx[@]+"${_git_ctx[@]}"} "$_target"; do
    if [[ "$_c" == *[[:cntrl:]]* ]]; then printf 'BLOCK\treset-unsafe-arg\n'; return; fi
    # odd positions hold a -C/--git-dir/--work-tree value
    # a leading tilde is expanded or not depending on quoting the scan cannot see
    if (( _n % 2 == 1 )) && [[ "$_c" == -* || "$_c" == '~'* ]]; then printf 'BLOCK\treset-unsafe-arg\n'; return; fi
    _n=$((_n + 1))
  done
  for _c in ${_git_ctx[@]+"${_git_ctx[@]}"}; do _joined="$_joined${_joined:+$_sep}$_c"; done
  # a credit counts for a top-level reset in the same context; a branch made elsewhere, or a
  # reset in nested text, leaves it a mutation
  for ((_n = 0; _n < ${#_credit_names[@]}; _n++)); do
    if (( _scan_depth == 0 && ! _NESTED_WRAPPER_BODY )) \
        && [[ "${_credit_ctx[_n]}" == "$_joined" ]]; then
      _cred="$_cred${_cred:+$_sep}${_credit_names[_n]}"
    elif (( ! _seqv )); then
      _seqv=1
    fi
  done
  [[ -z "$_cred" ]] || _credited_resets=$((_credited_resets + 1))
  # the credits field opens with C so an empty one keeps its place among the tab-split fields
  printf 'CHECK_RESET\t%s\t%s\t%s\t%s\tC%s\t%s\n' "$_seqv" "$_submod" "$_dyn" "$_target" \
    "$_cred" "$_joined"
}

# The segment mutates the repository unless it is a git call that only reads. A fetch that can
# prune or force-update refs, a remote edit, config handed in with -c, and output redirected to a
# file are not reads: the reset after them is judged against refs that no longer exist.
# $1 is how many credited resets came before this segment: a mutation after one may remove
# what its credits relied on (`git branch -D keep`), so it emits POST_MUTATION.
_note_segment_effect() {
  local _i _t _ro=0 _before=${1:-0}
  (( ${#_seg_tokens[@]} )) || return 0
  if _parse_git_invocation ""; then
    case "$_git_subcmd" in
      checkout|switch|rebase|bisect)
        for ((_i = _git_subcmd_index + 1; _i < ${#_seg_tokens[@]}; _i++)); do
          if _git_switch_token_risky "${_seg_tokens[_i]}"; then _git_prior_switch=1; fi
        done ;;
    esac
  fi
  if _parse_git_invocation "" && (( ! _git_has_cfg )); then
    case "$_git_subcmd" in
      status|log|show|diff|rev-parse|fetch|remote) _ro=1 ;;
    esac
    for ((_i = _git_subcmd_index + 1; _i < ${#_seg_tokens[@]} && _ro; _i++)); do
      _t=${_seg_tokens[_i]}
      case "$_t" in --output|--output=*|--ext-diff|--textconv) _ro=0 ;; esac
      case "$_git_subcmd" in
        fetch) case "$_t" in -p|--prune*|-f|--force|--update-head-ok|--refmap*|+*|*:*) _ro=0 ;; esac ;;
        remote) if (( _i == _git_subcmd_index + 1 )); then
                  case "$_t" in -v|--verbose|show|get-url) ;; *) _ro=0 ;; esac
                fi ;;
      esac
    done
  fi
  (( _ro )) && return 0
  _credit_branch_segment && return 0
  _git_prior_mutation=1
  (( _before == 0 )) || printf 'POST_MUTATION\n'
}

# One segment, classified in the order its commands run. `find -exec A ; -exec B` runs A and then
# B, so each part sees what the parts before it did (the leading `find` itself reads only).
_classify_segment() {
  local -a _all=(${_seg_tokens[@]+"${_seg_tokens[@]}"})
  local _n=${#_all[@]} _i _start=0 _split=0 _before=$_credited_resets
  for ((_i = 1; _i < _n; _i++)); do
    case "${_all[_i]}" in -exec|-execdir|-ok|-okdir) _split=1 ;; esac
  done
  if (( ! _split )); then
    _classify_force_push_segment
    _classify_reset_segment
    # the reset's own segment is not "after" it
    _note_segment_effect "$_before"
    return
  fi
  for ((_i = 1; _i <= _n; _i++)); do
    if (( _i < _n )); then
      case "${_all[_i]}" in -exec|-execdir|-ok|-okdir) ;; *) continue ;; esac
    fi
    _seg_tokens=("${_all[@]:_start:_i - _start}")
    _before=$_credited_resets
    _classify_force_push_segment
    _classify_reset_segment
    (( _start == 0 )) || _note_segment_effect "$_before"
    _start=$_i
  done
  _seg_tokens=("${_all[@]}")
}

# Code assembled from data (`echo '...' | bash`, `eval "$x"`, `$x`) runs text the scan
# never sees as code. When the command mentions `reset ... --ha` anywhere, a segment that
# runs such code emits one CHECK_RESET with dynamic target 2: the verdict blocks it on a
# protected branch only.
_text_mentions_reset=0
_unseen_code_seen=0

# Whether the shell at word $1 of the active segment runs code the scan cannot see: its stdin
# (-s, or no script operand: a pipe, a here-string, `bash <(...)`, whose words the lexer splits
# off), or a -c operand that holds an expansion or substitution.
_shell_runs_unseen_code() {
  local _j _t _c=0 _val=0
  for ((_j = $1 + 1; _j < ${#_seg_tokens[@]}; _j++)); do
    _t=${_seg_tokens[_j]}
    if (( _val )); then _val=0; continue; fi
    if (( _c )); then [[ "$_t" == *'$'* || "$_t" == *"$_DYNAMIC_TOKEN"* ]]; return; fi
    case "$_t" in
      --) _c=0; _val=0
          case "${_seg_tokens[_j + 1]-}" in ''|/dev/stdin|/dev/fd/*|-) return 0 ;; esac
          return 1 ;;
      --command=*) [[ "$_t" == *'$'* || "$_t" == *"$_DYNAMIC_TOKEN"* ]]; return ;;
      --command) _c=1 ;;
      -o|-O|+o|+O|--rcfile|--init-file) _val=1 ;;
      --*) ;;
      -) return 0 ;;
      -*s*|+*s*) [[ "$_t" == -* ]] && return 0 ;;
      -*c*) _c=1 ;;
      -*|+*) ;;
      /dev/stdin|/dev/fd/*) return 0 ;;
      *) return 1 ;;
    esac
  done
  return 0
}

# Emits the unseen-code record when the active segment, past its assignments and wrapper
# words, runs a shell that reads unseen code, `eval`, `source`/`.` of stdin, a process
# substitution or an expansion, or a command word spelled by an expansion or substitution.
# Reads only the segment.
_note_unseen_code() {
  (( _text_mentions_reset && ! _unseen_code_seen )) || return 0
  local _i _t _base _n=${#_seg_tokens[@]} _wrapped=0 _cmdpos=1 _hit=0 _op
  for ((_i = 0; _i < _n && ! _hit; _i++)); do
    _t=${_seg_tokens[_i]}
    if (( ${#_t} > 255 )); then _base=$_t; else _base=${_t##*/}; fi
    case "$_t" in [[:alpha:]_]=*|[[:alpha:]_][[:alnum:]_]*=*) continue ;; esac
    case "$_t" in '!'|if|while|until|do|then|else|elif|coproc) continue ;; esac
    case "$_base" in
      bash|sh|zsh|dash|ksh|fish) _shell_runs_unseen_code "$_i" && _hit=1 ;;
      eval) _hit=1 ;;
      source|.)
        _op=${_seg_tokens[_i + 1]-}
        case "$_op" in
          /dev/stdin|/dev/fd/*|*'$'*|*"$_DYNAMIC_TOKEN"*) _hit=1 ;;
          *) (( _seg_psub )) && _hit=1 ;;
        esac ;;
      # an expansion is the command only right where a command word stands
      '$'*|"$_DYNAMIC_TOKEN"*) (( _cmdpos )) && _hit=1 ;;
    esac
    (( _hit )) && break
    # git runs its words itself; anything else that is not a wrapper ends the search, except
    # after a wrapper, whose options and their values come before the command it runs
    [[ "$_base" == git ]] && return 0
    if _is_wrapper_prefix "$_base"; then _wrapped=1; _cmdpos=1; continue; fi
    (( _wrapped )) || return 0
    _cmdpos=0
  done
  (( _hit )) || return 0
  _unseen_code_seen=1
  printf 'CHECK_RESET\t%s\t0\t2\tHEAD\tC\t\n' "$(( _git_prior_switch ? 2 : 0 ))"
}

MAX_GIT_SCAN_DEPTH=4
# Why the coarse grep ran instead of the lexer: nesting too deep (default) or text too large.
_limit_reason=indeterminate
(( _oversize )) && _limit_reason=oversize

_scan_nested_text() {
  local _nested_text=$1 _nested_depth=$2
  # `${arr[@]+...}` keeps an empty array from tripping `set -u` on bash 3.2.
  local -a _saved_tokens=(${_seg_tokens[@]+"${_seg_tokens[@]}"})
  local -a _saved_here=(${_seg_here[@]+"${_seg_here[@]}"})
  local -a _saved_subs=(${_seg_subs[@]+"${_seg_subs[@]}"})
  local -a _saved_subhere_idx=(${_seg_subhere_idx[@]+"${_seg_subhere_idx[@]}"})
  local -a _saved_subhere_body=(${_seg_subhere_body[@]+"${_seg_subhere_body[@]}"})
  local _saved_saw_tab=$_seg_saw_tab _saved_redir=$_seg_redir
  scan_git_text "$_nested_text" "$((_nested_depth + 1))"
  _seg_tokens=(${_saved_tokens[@]+"${_saved_tokens[@]}"})
  _seg_here=(${_saved_here[@]+"${_saved_here[@]}"})
  _seg_subs=(${_saved_subs[@]+"${_saved_subs[@]}"})
  _seg_subhere_idx=(${_saved_subhere_idx[@]+"${_saved_subhere_idx[@]}"})
  _seg_subhere_body=(${_saved_subhere_body[@]+"${_saved_subhere_body[@]}"})
  _seg_saw_tab=$_saved_saw_tab
  _seg_redir=$_saved_redir
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
  local _depth=$1 _n=${#_seg_tokens[@]} _i _j _k _m _tok _base _body _args
  local _p=-1 _g=-1 _after=0 _end _runner=0 _prev="" _consumer=0 _isgit _cmdword=0 _rest _split
  local _wp=-1 _interp=-1 _cmdidx=-1
  for ((_i = 0; _i < _n; _i++)); do
    _tok=${_seg_tokens[_i]}
    if (( ${#_tok} > 255 )); then _base=$_tok; else _base=${_tok##*/}; fi
    [[ "$_base" == *"$_DYNAMIC_TOKEN"?* ]] && _base=${_base##*"$_DYNAMIC_TOKEN"}
    _is_shell_interpreter "$_base" && _consumer=1
    case "$_tok" in
      -exec|-execdir|-ok|-okdir) _p=-1; _wp=-1; _g=-1; _after=0; continue ;;
    esac
    (( _g < 0 )) || continue
    # only words before `git` can be the shell that runs a substitution's output
    if _is_shell_interpreter "$_base"; then (( _interp >= 0 )) || _interp=$_i; fi
    _isgit=0
    if [[ "$_base" == git ]] && _is_git_continuation "${_seg_tokens[_i + 1]-}"; then _isgit=1; fi
    case "$_base" in
      git)
        if (( _isgit )); then
          _g=$_i
        elif (( ! _after && ! _NESTED_WRAPPER_BODY && ! _seg_saw_tab )); then
          _g=$_n
        fi ;;
      [[:alpha:]_]=*|[[:alpha:]_][[:alnum:]_]*=*)
        # an assignment prefix makes everything after it arguments
        (( _p >= 0 )) || _p=$_i
        _after=1 ;;
      '!'|if|while|until|do|then|else|elif|coproc|"$_DYNAMIC_TOKEN"|"$_CURRENT_BRANCH_TOKEN") ;;
      *)
        if _is_wrapper_prefix "$_base"; then
          (( _p >= 0 )) || _p=$_i
          (( _wp >= 0 )) || _wp=$_i
          _after=1
        elif (( ! _after && ! _NESTED_WRAPPER_BODY && ! _seg_saw_tab )); then
          _g=$_n
        fi ;;
    esac
  done
  (( _g < _n )) || _g=-1
  for ((_i = 0; _i < _n; _i++)); do
    case "${_seg_tokens[_i]}" in
      [[:alpha:]_]=*|[[:alpha:]_][[:alnum:]_]*=*) continue ;;
      '!'|if|while|until|do|then|else|elif|coproc) continue ;;
      "$_DYNAMIC_TOKEN") _cmdword=1 ;;
    esac
    _cmdidx=$_i
    break
  done

  # Substitutions in the arguments run before the command they feed, so they are scanned first.
  for _body in ${_seg_subs[@]+"${_seg_subs[@]}"}; do
    if (( _p >= 0 || _cmdword )); then _scan_wrapper_operand "$_body" "$_depth"
    else _scan_nested_text "$_body" "$_depth"; fi
  done

  # A body that was itself handed to a wrapper has no visible prefix, but is still all arguments.
  # A tab anywhere in the segment, quoted or not, also makes the segment a wrapper call.
  if (( _p >= 0 || _NESTED_WRAPPER_BODY || _seg_saw_tab )); then
    _end=$(( _g >= 0 ? _g : _n ))
    for ((_i = (_p >= 0 ? _p : 0); _i < _end; _i++)); do
      _tok=${_seg_tokens[_i]}
      if (( ${#_tok} > 255 )); then _base=$_tok; else _base=${_tok##*/}; fi
      case "$_base" in
        bash|sh|zsh|dash|ksh|fish|su)
          for ((_j = _i + 1; _j < _n; _j++)); do
            case "${_seg_tokens[_j]}" in
              --command=*)
                _scan_wrapper_operand "${_seg_tokens[_j]#*=}" "$_depth"
                break ;;
              -c*|--command|-[!-]*c*)
                for ((_k = _j + 1; _k < _n; _k++)); do
                  if _has_code_text "${_seg_tokens[_k]}"; then
                    _body=${_seg_tokens[_k]}
                    _scan_wrapper_operand "$_body" "$_depth"
                    # arguments after the script are $0 $1 ...; rescan them in place when it uses them
                    case "$_body" in
                      *\$[0-9@*]*|*\$\{[0-9@*]*)
                        _args=""
                        for ((_m = _k + 1; _m < _n; _m++)); do _args="$_args ${_seg_tokens[_m]}"; done
                        [[ -n "$_args" ]] && _scan_wrapper_operand "$_body$_args" "$_depth" ;;
                    esac
                    break
                  fi
                done
                break ;;
            esac
          done
          _i=$_end ;;
        eval|ssh|watch)
          # these re-split their argv into one command line, so a word with spaces joins its
          # neighbours (`eval git "push -f" origin main` runs `git push -f origin main`)
          _rest=""; _split=0
          for ((_j = _i + 1; _j < _n; _j++)); do
            _rest="$_rest ${_seg_tokens[_j]}"
            if _has_code_text "${_seg_tokens[_j]}"; then _split=1; fi
          done
          if (( _split )); then _scan_wrapper_operand "$_rest" "$_depth"; fi ;;
        *)
          if (( _i > _p )) && _has_code_text "$_tok"; then
            _scan_wrapper_operand "$_tok" "$_depth"
          fi ;;
      esac
    done
  fi

  if (( _g >= 0 )); then
    for ((_i = _g + 1; _i < _n; _i++)); do
      _tok=${_seg_tokens[_i]}
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
        _tok=${_seg_tokens[_i]}
        _has_code_text "$_tok" || continue
        if [[ "$_tok" == -O?* ]]; then _tok=${_tok#-O}
        elif [[ "$_tok" == -*=* ]]; then _tok=${_tok#*=}; fi
        _scan_wrapper_operand "$_tok" "$_depth"
      done
    fi
  fi

  # A here-string is code only for a shell or a wrapper running one; `cat <<< 'text'` is data.
  if (( _p >= 0 || _consumer || _cmdword )); then
    for _body in ${_seg_here[@]+"${_seg_here[@]}"}; do
      _scan_wrapper_operand "$_body" "$_depth"
    done
  fi
  # A heredoc inside `$(cat ...)` is that word's value: code when the word is the command, an
  # argument of a shell, or sits between a wrapper and `git`. An assignment value or a word after
  # `git` is data.
  for ((_m = 0; _m < ${#_seg_subhere_body[@]}; _m++)); do
    _k=${_seg_subhere_idx[_m]}
    (( _k >= 0 )) || continue
    if (( _k == _cmdidx || (_interp >= 0 && _k > _interp) \
          || (_wp >= 0 && _k > _wp && (_g < 0 || _k < _g)) )); then
      _scan_wrapper_operand "${_seg_subhere_body[_m]}" "$_depth"
    fi
  done
}

# The substitutions an unquoted heredoc body expands are code even when the body is data.
# A lexer that dies here has seen nothing, so it reports `scan-failed` like the main scan.
_collect_heredoc_substitutions() {
  local _hd_kind _hd_value _hd_ok=0
  while IFS=$'\t' read -r _hd_kind _hd_value; do
    case "$_hd_kind" in
      NEST) _seg_subs+=("$_hd_value") ;;
      EOS) _hd_ok=1 ;;
    esac
  done < <(printf '%s' "$1" | LC_ALL=C awk -v dyn="$_DYNAMIC_TOKEN" -v cur="$_CURRENT_BRANCH_TOKEN" -v hdmode=1 "$_seg_token_awk")
  (( _hd_ok )) || printf 'BLOCK\tscan-failed\n'
}

scan_git_text() {
  local _scan_text=$1 _scan_depth=${2:-0} _kind _value _lex_ok=0
  if (( _scan_depth >= MAX_GIT_SCAN_DEPTH )); then
    if printf '%s\n' "$_scan_text" | tr -d "'\"\\\\[]{}" | tr '()`' '   ' | grep -Eq \
      'git([[:space:]].*)?[[:space:]]push([[:space:]].*)?[[:space:]](--force|--m(i(r(r(or?)?)?)?)?|-[[:alnum:]]*f[[:alnum:]]*|\+[^[:space:]]+)([[:space:];&|()`,]|$)'; then
      printf 'BLOCK\t%s\n' "$_limit_reason"
    elif (( _oversize )) && printf '%s\n' "$_scan_text" | LC_ALL=C grep -Eq \
      'git[[:space:]]([^;&|]*[[:space:]])?push[^;&|]*[{$`]'; then
      # no lexer ran, so a push whose words are spelled by a brace group or substitution cannot be read
      printf 'BLOCK\t%s\n' "$_limit_reason"
    elif printf '%s\n' "$_scan_text" | tr -d "'\"\\\\[]{}" | tr '()`' '   ' | grep -Eq \
      'git([[:space:]].*)?[[:space:]]reset([[:space:]].*)?[[:space:]]--h(a(rd?)?)?([[:space:];&|()`,]|$)'; then
      printf 'BLOCK\t%s-reset\n' "$_limit_reason"
    fi
    return
  fi
  _seg_tokens=()
  _seg_here=()
  _seg_subs=()
  _seg_subhere_idx=()
  _seg_subhere_body=()
  _seg_saw_tab=0
  _seg_redir=0
  # Every separator since this list began (the text, or after `;` or a newline) was `&&`.
  local _chain_and=1
  # The active segment holds a process substitution (for _note_unseen_code; nested scans keep
  # their own).
  local _seg_psub=0
  while IFS=$'\t' read -r _kind _value; do
    case "$_kind" in
      WORD) _seg_tokens+=("$_value") ;;
      NEST) _seg_subs+=("$_value") ;;
      HERE) _seg_here+=("$_value") ;;
      PSUB) _seg_psub=1 ;;
      UHERE)
        _seg_here+=("$_value")
        _collect_heredoc_substitutions "$_value" ;;
      SUBHERE)
        _seg_subhere_idx+=("${_value%%:*}")
        _seg_subhere_body+=("${_value#*:}") ;;
      TAB) _seg_saw_tab=1 ;;
      REDIR) _seg_redir=1 ;;
      EOS) _lex_ok=1 ;;
      SEP)
        _note_unseen_code
        _scan_known_wrapper_body "$_scan_depth"
        _classify_segment
        _seg_tokens=()
        _seg_here=()
        _seg_subs=()
        _seg_subhere_idx=()
        _seg_subhere_body=()
        _seg_saw_tab=0
        _seg_redir=0
        _seg_psub=0
        if [[ "$_value" != AND ]]; then
          # past another separator a later reset can run without the branch: a mutation again
          if (( _scan_depth == 0 && ${#_credit_names[@]} )); then
            _git_prior_mutation=1
            _credit_names=()
            _credit_ctx=()
          fi
          _chain_and=0
          [[ "$_value" == LIST ]] && _chain_and=1
        fi
        ;;
    esac
  done < <(printf '%s' "$_scan_text" | LC_ALL=C awk -v dyn="$_DYNAMIC_TOKEN" -v cur="$_CURRENT_BRANCH_TOKEN" "$_seg_token_awk")
  _note_unseen_code
  _scan_known_wrapper_body "$_scan_depth"
  _classify_segment
  (( _lex_ok )) || printf 'BLOCK\tscan-failed\n'
}

# Verdict half of the hard-reset check. It reads the repository the reset would touch, so every call
# goes through _rgit: no prompt, no index lock, and none of the user's own `-c` values (config can run
# a program inside the hook before approval). Filter drivers and fsmonitor are switched off per call.
_rgit() {
  GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 \
    git --no-pager -c core.fsmonitor=false ${_filter_off[@]+"${_filter_off[@]}"} \
    ${_rctx[@]+"${_rctx[@]}"} "$@" </dev/null 2>/dev/null
}

_reset_block() {
  echo "BLOCKED: git reset --hard $1" >&2
  exit 2
}

# Fills the caller's _rctx with the -C/--git-dir/--work-tree pairs of a record's context (joined
# by \x1f), for _rgit. Returns 1 when the context is malformed or holds a value git would misread,
# 2 when it depends on a session cwd that could not be entered (only an all-absolute context does
# not), 0 otherwise.
_resolve_git_ctx() {
  local -a _flat=()
  local _i _k _v
  _rctx=()
  if [[ -n "$1" ]]; then
    IFS=$'\x1f' read -r -a _flat <<< "$1"
  fi
  (( ${#_flat[@]} % 2 == 0 )) || return 1
  for ((_i = 0; _i < ${#_flat[@]}; _i += 2)); do
    _k=${_flat[_i]}
    _v=${_flat[_i + 1]}
    case "$_k" in -C|--git-dir|--work-tree) ;; *) return 1 ;; esac
    # a leading tilde is expanded by the shell or not depending on quoting the scan cannot see
    if [[ -z "$_v" || "$_v" == -* || "$_v" == '~'* || "$_v" == *[[:cntrl:]]* ]]; then return 1; fi
    _rctx+=("$_k" "$_v")
  done
  if (( _session_cwd_bad )); then
    (( ${#_rctx[@]} )) || return 2
    for ((_i = 1; _i < ${#_rctx[@]}; _i += 2)); do
      [[ "${_rctx[_i]}" == /* ]] || return 2
    done
  fi
  return 0
}

# Verdict for a force push of the current branch. $1 is CHECK_CURRENT, or CHECK_CURRENT_MAYBE when
# a substitution may spell the force flag; $2 the context. The branch is read from the repository
# the context names (else the session cwd's) through _rgit; symbolic-ref runs no filter driver, so
# the filter list is not read.
_push_current_verdict() {
  local _kind=$1 _ctxj=$2 _rc _branch _c _has_gd=0 _has_wt=0
  local -a _rctx=() _filter_off=()
  local _unres='unable to resolve branch for implicit force push'
  [[ "$_kind" == CHECK_CURRENT_MAYBE ]] \
    && _unres='unable to resolve branch for a push whose force flag a substitution may spell'
  [[ -z "$_ctxj" ]] || _unres="$_unres: the repository -C/--git-dir/--work-tree names"\
' cannot be resolved (check the path)'

  _rc=0
  _resolve_git_ctx "$_ctxj" || _rc=$?
  if (( _rc == 1 )); then echo "BLOCKED: $_unres" >&2; exit 2; fi
  if (( _rc == 2 )); then echo "BLOCKED: force push of the current branch $_cwd_gone" >&2; exit 2; fi
  # --work-tree alone keeps the cwd's repository and names no other; it stays blocked
  for _c in ${_rctx[@]+"${_rctx[@]}"}; do
    case "$_c" in --git-dir) _has_gd=1 ;; --work-tree) _has_wt=1 ;; esac
  done
  if (( _has_wt && ! _has_gd )); then
    echo 'BLOCKED: force push with --work-tree but no --git-dir cannot be attributed to a repository; add --git-dir or use -C' >&2
    exit 2
  fi

  # the full ref: `--short` prints `heads/main` when a tag named `main` exists
  _rc=0
  _branch=$(_rgit symbolic-ref -q HEAD) || _rc=$?
  # a detached HEAD pushes no branch by default
  (( _rc != 1 )) || return 0
  if (( _rc != 0 )) || [[ "$_branch" != refs/heads/?* ]]; then
    echo "BLOCKED: $_unres" >&2
    exit 2
  fi
  _branch=${_branch#refs/heads/}
  case "$_branch" in
    main|master|release/*) ;;
    *) return 0 ;;
  esac
  if [[ "$_kind" == CHECK_CURRENT_MAYBE ]]; then
    echo "BLOCKED: this may be a force push of current protected branch '$_branch' (a substitution can spell the force flag; spell it literally or use --force-with-lease)" >&2
  else
    echo "BLOCKED: force push of current protected branch '$_branch' (implicit upstream)" >&2
  fi
  exit 2
}

_reset_data_loss() {
  local _branch=$1 _what=$2
  {
    echo "BLOCKED: git reset --hard on protected branch '$_branch' would discard $_what."
    echo "  Keep the work first: run \`git switch -c <name>\` as its own command, then point '$_branch' where you want it, e.g. \`git branch -f $_branch origin/$_branch\`."
    echo '  Undo a commit but keep its changes: `git reset --soft HEAD~1` (staged) or `git reset HEAD~1`.'
    echo '  Throw edits away deliberately: `git restore --staged --worktree .` (plus `git clean -fd` for untracked files) or `git stash -u`.'
  } >&2
  exit 2
}

# Args: seq (0|1|2), submodules (0|1), dynamic target (0|1|2: 2 is code assembled from data,
# judged by the branch alone), target, context joined by \x1f,
# branch names created at HEAD earlier in the same `&&` chain, joined by \x1f.
_reset_verdict() {
  local _seq=$1 _submod=$2 _dyn=$3 _target=$4 _ctxj=$5 _credits=${6-}
  local -a _rctx=() _filter_off=() _cnames=()
  local _i _v _k _d _p _rc _branch _sha _top
  local _unresolved='could not be checked: the target repository or reset target cannot be resolved (check the -C/--git-dir/--work-tree path and the ref; quote a target that contains { }, e.g. '"'"'@{u}'"'"')'
  local _dirty='uncommitted changes (run `git status` first; stat-only differences also count)'

  _rc=0
  _resolve_git_ctx "$_ctxj" || _rc=$?
  (( _rc != 1 )) || _reset_block "$_unresolved"
  (( _rc != 2 )) || _reset_block "$_cwd_gone"

  if ! _rgit rev-parse --git-dir >/dev/null; then
    # nothing named a repository and the cwd is none: git fails on its own, or a `cd` came first (documented gap)
    (( ${#_rctx[@]} )) && _reset_block "$_unresolved"
    return 0
  fi
  if (( _seq == 2 )); then
    _reset_block "follows a command that may switch to a protected branch, so the branch cannot be read yet; run the switch as its own command first, then reset"
  fi
  _rc=0
  _v=$(_rgit config --name-only --get-regexp '^filter\..*\.(clean|process)$') || _rc=$?
  # 1 means no driver is set; any other failure is a config git could not read, not "no filters"
  (( _rc <= 1 )) || _reset_block "$_unresolved"
  while IFS= read -r _k; do
    case "$_k" in
      *.clean) _d=${_k%.clean} ;;
      *.process) _d=${_k%.process} ;;
      *) continue ;;
    esac
    _d=${_d#filter.}
    # `-c` splits a key at its first `=`, so such a driver name could not be switched off
    if [[ "$_d" == *=* || "$_d" == *[[:cntrl:]]* ]]; then _reset_block "$_unresolved"; fi
    _filter_off+=(-c "filter.$_d.clean=" -c "filter.$_d.process=" -c "filter.$_d.required=false")
  done <<< "$_v"

  # the full ref: `--short` prints `heads/main` when a tag named `main` exists
  _rc=0
  _branch=$(_rgit symbolic-ref -q HEAD) || _rc=$?
  if (( _rc == 1 )); then return 0; fi
  if (( _rc != 0 )) || [[ "$_branch" != refs/heads/?* ]]; then _reset_block "$_unresolved"; fi
  _branch=${_branch#refs/heads/}
  case "$_branch" in main|master|release/*) ;; *) return 0 ;; esac

  if (( _dyn == 2 )); then
    _p='code assembled from data that runs `git reset --hard` cannot be checked;'
    echo "BLOCKED: $_p run the reset directly (protected branch '$_branch')" >&2
    exit 2
  fi
  if (( _dyn )); then
    _reset_block "on protected branch '$_branch' has a dynamic target or flag that cannot be checked; spell it literally"
  fi
  if (( _seq )); then
    _reset_block "on protected branch '$_branch' follows another command in the same line that may change the repository; run the earlier steps as their own command first, then reset"
  fi
  _v=$(_rgit config --bool submodule.recurse) || true
  if (( _submod )) || [[ "$_v" == true ]]; then
    _reset_block "on protected branch '$_branch' with submodule recursion cannot be checked; reset without --recurse-submodules"
  fi
  _rgit rev-parse --verify -q 'HEAD^{commit}' >/dev/null \
    || _reset_block "on protected branch '$_branch' cannot be checked: the branch has no commits yet"
  _sha=$(_rgit rev-parse --verify -q --end-of-options "$_target^{commit}") || _sha=""
  [[ -n "$_sha" ]] || _reset_block "$_unresolved"

  _rc=0
  # submodule content is not touched by a flat reset, and inspecting it would read the submodule's own config
  _rgit diff-index --cached --quiet --ignore-submodules=all HEAD -- || _rc=$?
  if (( _rc == 1 )); then _reset_data_loss "$_branch" "$_dirty"; fi
  (( _rc == 0 )) || _reset_block "$_unresolved"
  _rc=0
  _rgit diff-files --quiet --ignore-submodules=all || _rc=$?
  if (( _rc == 1 )); then _reset_data_loss "$_branch" "$_dirty"; fi
  (( _rc == 0 )) || _reset_block "$_unresolved"

  # a file the target adds and the work tree already holds is untracked: the reset overwrites it
  _top=$(_rgit rev-parse --show-toplevel) || _top=""
  [[ -n "$_top" ]] || _reset_block "$_unresolved"
  _rgit diff-tree -r -z --name-only --no-renames --diff-filter=A HEAD "$_sha" -- >/dev/null \
    || _reset_block "$_unresolved"
  while IFS= read -r -d '' _v; do
    # the path itself, and every parent: a plain file or a symlink standing where a directory is needed
    _p=$_v
    while :; do
      if [[ -L "$_top/$_p" ]] || { [[ -e "$_top/$_p" ]] && { [[ "$_p" == "$_v" ]] || [[ ! -d "$_top/$_p" ]]; }; }; then
        _reset_data_loss "$_branch" 'untracked files that the target commit would overwrite'
      fi
      [[ "$_p" == */* ]] || break
      _p=${_p%/*}
    done
  done < <(_rgit diff-tree -r -z --name-only --no-renames --diff-filter=A HEAD "$_sha" --)

  # A branch the command creates first sits at HEAD and keeps every commit the reset drops,
  # but only if `git branch` can create it: a valid name that no branch holds yet.
  if [[ -n "$_credits" ]]; then
    IFS=$'\x1f' read -r -a _cnames <<< "$_credits"
    for _k in ${_cnames[@]+"${_cnames[@]}"}; do
      _p="on protected branch '$_branch' counts on branch '$_k' created earlier in this command"
      _rgit check-ref-format --branch "$_k" >/dev/null \
        || _reset_block "$_p, but '$_k' is not a valid branch name, so it keeps nothing;"\
' create the branch as its own command first, then reset'
      _rc=0
      _rgit rev-parse --verify -q "refs/heads/$_k" >/dev/null || _rc=$?
      if (( _rc == 0 )); then
        _reset_block "$_p, but '$_k' already exists, so it is not created at HEAD and"\
' nothing may keep the commits the reset drops; pick a new name, or create the branch as'\
' its own command first, then reset'
      fi
      (( _rc == 1 )) || _reset_block "$_unresolved"
    done
    return 0
  fi

  _rc=0
  _v=$(_rgit rev-list --max-count=1 HEAD --not "$_sha" --exclude="$_branch" --branches --remotes --tags) || _rc=$?
  (( _rc == 0 )) || _reset_block "$_unresolved"
  [[ -z "$_v" ]] || _reset_data_loss "$_branch" 'commits not on any other branch, tag or remote'
  return 0
}

# The scan reads only text and runs to completion first; the verdicts, which read the repository,
# then judge its records in order. The scanner ends with DONE; a missing sentinel means it died
# mid-scan, which must not read as "clean". Runs as a background job: exit 0 allows, 2 blocks.
# USR2 tells the hook the scan is done, so a timeout can say which half ran out of time.
_scan_and_judge() {
  local -a _records=()
  local _line _policy _reason _rseq _rsub _rdyn _rtarget _rcred _rctx _i _last_post=-1
  # the depth-cap grep, relaxed: any `reset ... --ha` in the text, quoted or not
  if [[ "$_bj" == *reset* ]] && printf '%s\n' "$_bj" | tr -d "'\"\\\\[]{}" | tr '()`' '   ' \
      | grep -Eq 'reset([[:space:]].*)?[[:space:]]--ha'; then
    _text_mentions_reset=1
  fi
  while IFS= read -r _line; do _records+=("$_line"); done < <(scan_git_text "$_bj" "$(( _oversize ? MAX_GIT_SCAN_DEPTH : 0 ))"; printf 'DONE\n')
  kill -USR2 $$
  if (( ! ${#_records[@]} )) || [[ "${_records[${#_records[@]} - 1]}" != DONE ]]; then
    echo 'BLOCKED: git command scan did not complete (internal error)' >&2
    exit 2
  fi
  # POST_MUTATION voids the credits of every CHECK_RESET before it: that reset then gets the
  # full loss check, with no branch from earlier in the command counted
  for ((_i = 0; _i < ${#_records[@]}; _i++)); do
    [[ "${_records[_i]}" == POST_MUTATION ]] && _last_post=$_i
  done
  for ((_i = 0; _i < ${#_records[@]}; _i++)); do
    IFS=$'\t' read -r _policy _reason <<< "${_records[_i]}"
    _judge_record
  done
  exit 0
}

_judge_record() {
  case "$_policy" in
    BLOCK)
      case "$_reason" in
        all-refs) echo 'BLOCKED: force push of all refs may update protected branches' >&2 ;;
        scan-failed) echo 'BLOCKED: git command scan did not complete (internal error)' >&2 ;;
        reset-env) echo 'BLOCKED: git reset --hard with GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE/GIT_COMMON_DIR or injected GIT_CONFIG_* set can point git at a repository or config that cannot be checked; unset it or use -C (GIT_CONFIG_NOSYSTEM and GIT_CONFIG_GLOBAL/SYSTEM=/dev/null are fine)' >&2 ;;
        reset-config) echo 'BLOCKED: git reset --hard with -c core.worktree/core.bare redirects the work tree and cannot be checked; drop the override' >&2 ;;
        reset-dynamic-context) echo 'BLOCKED: git reset --hard with a dynamic -C/--git-dir/--work-tree value cannot be checked; spell the path literally' >&2 ;;
        reset-unsafe-arg) echo 'BLOCKED: git reset --hard with a control character, a dash-led value, or a ~ path cannot be checked safely; spell the absolute path plainly' >&2 ;;
        reset-work-tree) echo 'BLOCKED: git reset --hard with --work-tree but no --git-dir resets another tree under this directory'"'"'s repository; add --git-dir or use -C' >&2 ;;
        oversize-reset) echo 'BLOCKED: git reset --hard in a command too large to scan exactly; split the command' >&2 ;;
        indeterminate-reset) echo 'BLOCKED: git reset --hard nested too deeply to scan; spell the reset directly' >&2 ;;
        dynamic-destination) echo 'BLOCKED: force push with a dynamic destination or flag cannot be checked; spell the branch literally or use --force-with-lease' >&2 ;;
        context-destination) echo 'BLOCKED: force push into a repository the command does not spell (a GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE/GIT_COMMON_DIR/GIT_CONFIG_* assignment, or an expansion, substitution or control character in git'"'"'s -C/--git-dir/--work-tree or other global options) cannot be attributed to a branch; spell the path literally or name the refspec' >&2 ;;
        indeterminate) echo 'BLOCKED: force push nested too deeply to scan; spell the push directly or use --force-with-lease' >&2 ;;
        oversize) echo 'BLOCKED: force push in a command too large to scan exactly; split the command or use --force-with-lease' >&2 ;;
        *) echo 'BLOCKED: force push to protected branch (main/master/release/*)' >&2 ;;
      esac
      exit 2
      ;;
    CHECK_RESET)
      IFS=$'\t' read -r _rseq _rsub _rdyn _rtarget _rcred _rctx <<< "$_reason"
      _rcred=${_rcred#C}
      (( _i > _last_post )) || _rcred=""
      _reset_verdict "$_rseq" "$_rsub" "$_rdyn" "$_rtarget" "${_rctx-}" "$_rcred"
      ;;
    CHECK_CURRENT|CHECK_CURRENT_MAYBE)
      _push_current_verdict "$_policy" "${_reason-}"
      ;;
  esac
}

# One bounded job instead of a timeout at every git call: a repository config can make git hang
# (a FIFO include), and the hook must answer before its caller kills it (Pi at 5 s). The job gets its
# own process group (set -m) so the watchdog's signal can kill every git it started. The watchdog's
# stdio is detached so a caller waiting for the hook's output to close is not held up by it.
# The session's cwd from the payload, entered here so the job inherits it and a relative -C or
# --git-dir resolves as it will for the user. A present cwd that is relative or no longer exists
# (a deleted worktree) cannot be entered: a verdict that depends on the cwd then blocks.
_session_cwd_bad=0
_session_cwd=$(jq -r '.cwd // empty' <<< "$payload") || _session_cwd=.
if [[ -n "$_session_cwd" ]]; then
  if [[ "$_session_cwd" != /* || ! -d "$_session_cwd" ]] || ! CDPATH='' cd -P -- "$_session_cwd" 2>/dev/null; then
    _session_cwd_bad=1
  fi
fi
_cwd_gone='cannot be checked: the session'"'"'s working directory no longer exists or is not an absolute path; cd to an existing directory and retry'

_budget=3
if [[ "${SWE_WORKBENCH_GUARD_GIT_BUDGET-}" =~ ^([0-9]+)(\.[0-9]+)?$ ]]; then
  _bint=${BASH_REMATCH[1]}
  _bint=${_bint#"${_bint%%[!0]*}"}
  if [[ -z "$_bint" ]]; then _budget=1
  elif (( ${#_bint} > 1 || _bint >= 3 )); then _budget=3
  else _budget=$SWE_WORKBENCH_GUARD_GIT_BUDGET
  fi
fi
_vpid=""
_wpid=""
_scanned=0
trap 'kill -TERM -"$_vpid" 2>/dev/null; kill -KILL -"$_vpid" 2>/dev/null' USR1
trap '_scanned=1' USR2
# the job and the watchdog sit in their own process groups, so a caller killing the hook would
# leave them running
trap 'kill -KILL -- -"$_vpid" -"$_wpid" 2>/dev/null; exit 2' TERM INT HUP
set -m
_scan_and_judge </dev/null &
_vpid=$!
( sleep "$_budget"; kill -USR1 $$ ) </dev/null >/dev/null 2>&1 &
_wpid=$!
# A trapped signal interrupts the wait. After USR2 the job is still running, so wait again; after
# USR1 it was killed in the trap, so its status is neither 0 nor 2.
_vrc=0
wait "$_vpid" || _vrc=$?
if (( _vrc > 128 && _scanned )); then
  _vrc=0
  wait "$_vpid" || _vrc=$?
fi
trap '' USR1 USR2
trap - TERM INT HUP
kill -TERM -"$_wpid" 2>/dev/null
wait "$_wpid" 2>/dev/null
wait "$_vpid" 2>/dev/null
set +m
case "$_vrc" in
  0) ;;
  2) exit 2 ;;
  *)
    if (( _scanned )); then
      echo 'BLOCKED: git command could not be checked in time (a repository config may be hanging git)' >&2
    else
      echo 'BLOCKED: git command scan did not finish in time (the command is too long to check; split it into smaller commands)' >&2
    fi
    exit 2
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
    # Oversize text skips the segmenter: `pi` and a print flag anywhere in it count as one segment.
    if (( _oversize )); then
      pi_seg=$norm
    else
      pi_seg=$(printf '%s' "$_bj" | LC_ALL=C awk "$_segment_awk") || _fail_closed awk
    fi
    # Byte-wise matching: the patterns are ASCII, and a case-insensitive multibyte grep over a
    # 64 KB+ line is several times slower on GNU grep.
    if printf '%s\n' "$pi_seg" | LC_ALL=C grep -iE '(^|[[:space:]])([^[:space:]]*/)?pi[[:space:]]' \
       | LC_ALL=C grep -Eq '(^|[[:space:]])(-p|--print)([[:space:]]|=|$)'; then
      if (( _oversize )); then
        echo 'BLOCKED: command over 64 KB mentions pi and -p/--print, which cannot be told apart from a nested pi session without the segmenter; split the command' >&2
      else
        echo 'BLOCKED: nested non-interactive pi session (subagent recursion guard)' >&2
      fi
      exit 2
    fi
    ;;
esac

exit 0
