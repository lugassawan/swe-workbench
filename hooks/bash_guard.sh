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
#     docs/decisions-task-dispatch.md)
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
# --force-with-lease/--force-if-includes intentionally unblocked (#163); force-push after a shell
# separator (`&& echo main`) may over-block via the folded input (accepted fail-safe); a remote
# literally named main/master over-blocks. Block 2's push-token scan trusts a small allowlist of
# known BOOLEAN-only push flags and defensively consumes the next token for any other `-*` flag
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

if echo "$norm" | grep -Eq 'git[[:space:]]+push.*(--force([[:space:]]|$)|(^|[[:space:]])-f([[:space:]]|$))' \
   && echo "$norm" | grep -Eq '(^|[[:space:]]|:)(main|master|release/[^[:space:]:]*)([[:space:]]|:|$)'; then
  echo 'BLOCKED: force push to protected branch (main/master/release/*)' >&2
  exit 2
fi

# Block 2: implicit-branch force-push from a protected branch — additive to the
# explicit-refspec block above. Force detection reuses the SAME anchored pattern,
# so --force-with-lease stays unblocked (settled: #163). Fires ONLY when no
# explicit refspec is present (push relies on push.default/upstream); an explicit
# non-protected refspec (`origin feat`) must stay allowed even from a protected
# branch — Block 1 already owns explicit protected refspecs.
if echo "$norm" | grep -Eq 'git[[:space:]]+push.*(--force([[:space:]]|$)|(^|[[:space:]])-f([[:space:]]|$))'; then
  # Isolate the FORCE-flagged push invocation from the comment-stripped,
  # backslash-joined command ($_bj keeps real separators). Fold the SAME
  # separator alphabet as $_norm (;|&\n\t, not just ;|&) so a tab/newline-
  # prefixed command doesn't leak extra tokens onto the push line, and filter
  # to lines that actually match the force pattern — a chained non-force
  # `git push` (e.g. `git push origin x && git push --force`) must not be the
  # one inspected for a refspec, or the real force-push line is skipped
  # entirely (#501 review).
  push_cmd=$(printf '%s' "$_bj" | tr ';|&\n\t' '\n\n\n\n\n' \
    | grep -E 'git[[:space:]]+push.*(--force([[:space:]]|$)|(^|[[:space:]])-f([[:space:]]|$))' \
    | tr -d "'\"" | head -n1)
  has_refspec=0; seen_positional=0; consume_next=0
  read -ra _toks <<<"$push_cmd"
  if (( ${#_toks[@]} )); then                 # guard: bash 3.2 + set -u errors on empty "${arr[@]}"
    for _t in "${_toks[@]}"; do
      if (( consume_next )); then             # swallow an unrecognized flag's separate-word value
        consume_next=0
        continue
      fi
      case "$_t" in
        git|push) ;;                          # command words
        # Known BOOLEAN-only push flags — safe to skip outright. An
        # unrecognized `-*` flag (senior-engineer consult, #501: `-o <val>`
        # miscounted as a positional and silently allowed the push through)
        # is assumed to take a separate-word value and that value is
        # consumed too, so it can never be mistaken for the remote/refspec.
        --force|-f|--force-with-lease*|--force-if-includes|--all|--tags|--follow-tags|\
        --prune|--thin|--atomic|--no-verify|--dry-run|--porcelain|-q|--quiet|-v|--verbose|\
        --progress|--no-progress|-u|--set-upstream|-d|--delete|--signed|--no-signed|\
        --mirror|-n) ;;
        -*) consume_next=1 ;;                 # unrecognized flag — assume it takes a value
        *:*) has_refspec=1; break ;;          # src:dst refspec
        *) if (( seen_positional )); then has_refspec=1; break; fi; seen_positional=1 ;;  # 1st bareword = remote
      esac
    done
  fi
  if (( has_refspec == 0 )); then             # relies on push.default / upstream
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    case "$branch" in
      main|master|release/*)
        echo "BLOCKED: force push of current protected branch '$branch' (implicit upstream)" >&2
        exit 2
        ;;
    esac
  fi
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
    pi_seg=$(printf '%s' "$_bj" | awk '
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
      }')
    if printf '%s\n' "$pi_seg" | grep -iE '(^|[[:space:]])([^[:space:]]*/)?pi[[:space:]]' \
       | grep -Eq '(^|[[:space:]])(-p|--print)([[:space:]]|=|$)'; then
      echo 'BLOCKED: nested non-interactive pi session (subagent recursion guard)' >&2
      exit 2
    fi
    ;;
esac

exit 0
