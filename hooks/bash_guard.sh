#!/usr/bin/env bash
# PreToolUse:Bash guard — block destructive commands and short-circuit safe ones.
#
# Blocks:
#   - rm -rf against /, /*, ~, $HOME, /Users[/<user>], /home[/<user>]
#   - git push --force / -f to main/master/release/*
#   - git reset --hard on main/master/release/*
#
# Short-circuits (exit 0, no greps) for commands that contain neither "rm" nor
# "git". This is the common case (ls, cat, echo, make, npm, …) and removes the
# per-call grep tax flagged in #233.
#
# Out of scope: ${HOME} brace-form; ANSI-C $'...' quoting; path normalization via .. traversal; compound cd (cwd not in hook payload).
# --force-with-lease/--force-if-includes intentionally unblocked (#163); force-push after a shell
# separator (`&& echo main`) may over-block via the folded input (accepted fail-safe); a remote
# literally named main/master over-blocks. Block 2's push-token scan trusts a small allowlist of
# known BOOLEAN-only push flags and defensively consumes the next token for any other `-*` flag
# (assumes it takes a separate-word value, e.g. `-o ci.skip`) so an unknown flag's value can never
# be miscounted as the remote/refspec (#501 senior-engineer consult); an unrecognized flag that
# actually takes NO value will over-block by one token (fail-safe direction, not a bypass).

set -u

if ! cmd=$(jq -r '.tool_input.command // ""'); then
  echo 'bash_guard: jq parse error — blocking by default' >&2
  exit 2
fi

# Strip shell comments per-line BEFORE folding newlines. A `#` comment ends at
# its line's newline; folding first would let an early comment swallow a
# destructive command on a later line (e.g. "echo hi # note\nrm -rf ~").
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

# Normalise separators AND newlines/tabs to spaces so rm/git after ; | & \n \t
# are still detected — the fast-gate `case` and the grep detectors must share
# ONE separator alphabet (the bug in #501: gate saw ';|&', grep saw [[:space:]]).
_norm=$(printf '%s' "$_nc" | tr ';|&\n\t' '     ')

case "$_norm" in
  rm\ *|*\ rm\ *|*\(*rm\ *|*git*) ;;
  *)                              exit 0 ;;
esac

# Strip quotes and bracket metacharacters that could mask paths.
norm=$(printf '%s' "$_norm" | tr -d "'\"()[]{}")

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
  # Isolate the FORCE-flagged push invocation from the comment-stripped raw
  # command ($_nc keeps real separators). Fold the SAME separator alphabet as
  # $_norm (;|&\n\t, not just ;|&) so a tab/newline-prefixed command doesn't
  # leak extra tokens onto the push line, and filter to lines that actually
  # match the force pattern — a chained non-force `git push` (e.g. `git push
  # origin x && git push --force`) must not be the one inspected for a
  # refspec, or the real force-push line is skipped entirely (#501 review).
  push_cmd=$(printf '%s' "$_nc" | tr ';|&\n\t' '\n\n\n\n\n' \
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

exit 0
