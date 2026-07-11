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
# Stdout contract (eval-safe KEY=VALUE, %q-quoted path fields):
#   MERGE_BASE=<sha>                        echoed back verbatim
#   CANDIDATE id=<n> path=<p> refs=<count>  one per whole file the branch ADDED
#                                            (git diff --diff-filter=A, renames
#                                            excluded via -M so a relocated-but-
#                                            unmodified file is never a candidate)
#   CANDIDATES=<n>                          count of CANDIDATE lines above
#   MAIN_ADD path=<p>                       one per file the default branch
#                                            added or changed in the same window
#
# refs=<count> is an inbound-reference guard: how many other tracked files
# mention the candidate's path-stem (basename without extension). refs=0 is
# necessary (not sufficient) for the caller's auto-apply tier — any nonzero
# refs must escalate to a human, never auto-apply.
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

id=0
while IFS=$'\t' read -r status path; do
  [ "$status" = "A" ] || continue
  id=$((id + 1))
  stem=$(basename "$path")
  stem="${stem%.*}"
  refs=$(git grep -l --fixed-strings -e "$stem" -- ":(exclude,literal)$path" 2>/dev/null | wc -l | tr -d ' ') || true
  printf 'CANDIDATE id=%d path=%q refs=%d\n' "$id" "$path" "$refs"
done < <(git diff --name-status -M "$MERGE_BASE".."$PRE_SYNC_HEAD")

printf 'CANDIDATES=%d\n' "$id"

while IFS=$'\t' read -r _status path; do
  printf 'MAIN_ADD path=%q\n' "$path"
done < <(git diff --name-status -M --diff-filter=AM "$MERGE_BASE".."$DEFAULT_REF")
