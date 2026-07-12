#!/usr/bin/env bash
# Gathers `sync --check-redundancy` candidates: whole files the branch added
# since the merge-base, cross-referenced against what the default branch grew
# independently in the same window. Pure function of its three SHA/ref
# arguments — no hidden temporal coupling on current HEAD, so it stays
# testable and correct even after Step 3's mechanical sync has moved HEAD.
#
# Usage: redundancy-scope.sh <merge-base> <pre-sync-head> <default-ref>
#   <merge-base> may be empty (unrelated-history repos) — the script then
#   short-circuits with CANDIDATES=0 and no CANDIDATE/MAIN_ADD lines.
#
# Stdout contract: MERGE_BASE=<sha> and CANDIDATES=<n> are plain eval-safe
# KEY=VALUE lines. CANDIDATE/MAIN_ADD lines are structured records, not
# eval-safe as a whole — parse their fields; their path=%q value is quoted
# only so it round-trips safely if a field is extracted and re-used as shell
# input.
#   MERGE_BASE=<sha>                        echoed back verbatim
#   CANDIDATE id=<n> path=<p> refs=<count>  one per whole file the branch ADDED
#                                            (git diff --diff-filter=A, renames
#                                            excluded via -M so a relocated-but-
#                                            unmodified file is never a candidate.
#                                            Caveat: -M's similarity heuristic is
#                                            content-based, not semantic — an
#                                            unrelated add+delete in the same
#                                            commit can score as a rename and
#                                            silently skip CANDIDATE enumeration;
#                                            accepted as a safe-direction miss,
#                                            not a misfire.)
#   CANDIDATES=<n>                          count of CANDIDATE lines above
#   MAIN_ADD path=<p>                       one per file the default branch
#                                            added or changed in the same window
#
# refs=<count> is an inbound-reference guard: how many other tracked files
# mention the candidate's path-stem (basename without extension), EXCLUDING
# the candidate itself and main's newly-ADDED counterpart files (status A in
# the MAIN_ADD diff — NOT every MAIN_ADD path, since a file main merely
# MODIFIED for an unrelated reason can still carry a genuine live reference
# to the candidate, and swallowing that into the exclusion set would hide a
# real inbound reference). The exclusion matters because this script runs
# (via Step 6) after Step 3's mechanical sync has already merged the default
# branch in — the working tree at that point contains both the candidate and
# its main-side counterpart, and without excluding that counterpart, a
# genuine whole-file duplicate always counts its own counterpart as a
# "reference" and can never reach refs=0. refs=0 is necessary (not
# sufficient) for the caller's auto-apply tier — any nonzero refs must
# escalate to a human, never auto-apply.
#
# Exit non-zero only if the cwd is not inside a git work tree, or a required
# argument is missing.
set -euo pipefail

MERGE_BASE="${1-}"
PRE_SYNC_HEAD="${2:?Usage: redundancy-scope.sh <merge-base> <pre-sync-head> <default-ref>}"
DEFAULT_REF="${3:?Usage: redundancy-scope.sh <merge-base> <pre-sync-head> <default-ref>}"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "redundancy-scope: not inside a git work tree" >&2; exit 1; }

printf 'MERGE_BASE=%s\n' "$MERGE_BASE"

if [ -z "$MERGE_BASE" ]; then
  printf 'CANDIDATES=0\n'
  exit 0
fi

MAIN_ADD_PATHS=()
MAIN_NEW_PATHS=()
while IFS=$'\t' read -r status path; do
  MAIN_ADD_PATHS+=("$path")
  [ "$status" = "A" ] && MAIN_NEW_PATHS+=("$path")
done < <(git diff --name-status -M --diff-filter=AM "$MERGE_BASE".."$DEFAULT_REF")

id=0
while IFS=$'\t' read -r status path; do
  [ "$status" = "A" ] || continue
  id=$((id + 1))
  stem=$(basename "$path")
  stem="${stem%.*}"
  [ -z "$stem" ] && stem=$(basename "$path")

  exclude_args=(":(exclude,literal)$path")
  if [ "${#MAIN_NEW_PATHS[@]}" -gt 0 ]; then
    for main_path in "${MAIN_NEW_PATHS[@]}"; do
      exclude_args+=(":(exclude,literal)$main_path")
    done
  fi
  refs=$(git grep -l --fixed-strings -e "$stem" -- "${exclude_args[@]}" 2>/dev/null | wc -l | tr -d ' ') || true
  printf 'CANDIDATE id=%d path=%q refs=%d\n' "$id" "$path" "$refs"
done < <(git diff --name-status -M "$MERGE_BASE".."$PRE_SYNC_HEAD")

printf 'CANDIDATES=%d\n' "$id"

if [ "${#MAIN_ADD_PATHS[@]}" -gt 0 ]; then
  for path in "${MAIN_ADD_PATHS[@]}"; do
    printf 'MAIN_ADD path=%q\n' "$path"
  done
fi
