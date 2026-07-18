#!/usr/bin/env bash
# PR-scoped backstop: force-removes residual ephemeral artifacts left behind by
# workflow-pr-review, workflow-pr-review-followup, and workflow-address-feedback
# for one specific PR number — rimba worktrees (pr-review-<N>, pr-followup-<N>,
# address-feedback-<N>) and their /tmp/swe-workbench-* state-file JSON.
#
# Invoked by workflow-cleanup-merged's Residual Sweep step AFTER it has already
# independently verified via `gh pr view` that PR <N> is MERGED — so it is safe
# to force-remove anything keyed to that specific N. Reviewer-flow worktrees
# (pr-review-<N>, pr-followup-<N>) also get their branch force-deleted, since
# those are throwaway detached review copies. address-feedback-<N> worktrees
# get ONLY their worktree removed — their branch may be the PR's real head
# branch, so it is never touched here.
#
# Usage: sweep-residuals.sh <PR number>
# Stdout contract (always emitted, even on a non-integer arg or nothing found):
#   SWEPT_WORKTREES=<n>    — count of ephemeral worktrees removed (0-3)
#   SWEPT_STATE_FILES=<n>  — count of /tmp state files removed
#   RESIDUAL_NONE=0|1      — 1 iff both counts above are 0
# Always exits 0 — the caller's `eval "$(...)"` must never abort mid-cleanup.
set -euo pipefail

emit_clean_contract() {
  printf 'SWEPT_WORKTREES=0\nSWEPT_STATE_FILES=0\nRESIDUAL_NONE=1\n'
}

N="${1:-}"

# Non-integer (or missing) arg: emit the clean contract and exit 0 — never abort
# the caller's eval chain over a malformed argument.
case "$N" in
  ''|*[!0-9]*)
    emit_clean_contract
    exit 0
    ;;
esac

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) || { emit_clean_contract; exit 0; }
ROOT_DIR=$(cd "$SCRIPT_DIR/../../.." && pwd) || { emit_clean_contract; exit 0; }
RUNTIME_DIR="$ROOT_DIR/runtime"
RIMBA=$("$SCRIPT_DIR/resolve-rimba.sh" 2>/dev/null) || RIMBA=""

SWEPT_WORKTREES=0
SWEPT_STATE_FILES=0

# ── Block A: state-file reap (independent of git; candidates are fixed by the
# three flows' own naming conventions) ──────────────────────────────────────

STATE_FILES=(
  "/tmp/swe-workbench-pr-review/$N.json"
  "/tmp/swe-workbench-pr-review/$N-followup.json"
  "/tmp/swe-workbench-address-feedback/$N.json"
  "/tmp/swe-workbench-address-feedback/$N-threads.json"
  "/tmp/swe-workbench-address-feedback/$N-pr-comments.json"
  "/tmp/swe-workbench-address-feedback/$N-triage.json"
)
# workflow-pr-review-post scopes its own cache by CALLER_TAG (general, followup,
# a specialist review mode, ...) — nullglob-scoped so a no-match glob expands to
# zero words instead of the literal pattern (and never trips `set -u` the way an
# empty array element expansion would on bash 3.2).
shopt -s nullglob
for f in /tmp/swe-workbench-pr-review/"$N"-post-threads-*.json; do
  STATE_FILES+=("$f")
done
shopt -u nullglob

TO_REAP=()
for f in "${STATE_FILES[@]}"; do
  [ -e "$f" ] && TO_REAP+=("$f")
done

if [ "${#TO_REAP[@]}" -gt 0 ]; then
  # clean-state-files.sh validates all args before deleting any and exits 1 on
  # the first invalid one — never let that abort us under set -e.
  "$RUNTIME_DIR/clean-state-files.sh" "${TO_REAP[@]}" >/dev/null 2>&1 || true
  for f in "${TO_REAP[@]}"; do
    [ -e "$f" ] || SWEPT_STATE_FILES=$((SWEPT_STATE_FILES + 1))
  done
fi

# ── Block B: worktree + branch reap ─────────────────────────────────────────

MAIN_REPO=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}') || true

if [ -n "${MAIN_REPO:-}" ]; then
  cd "$MAIN_REPO"

  PR_REVIEW_LABEL="pr-review-$N"
  PR_FOLLOWUP_LABEL="pr-followup-$N"
  ADDR_FEEDBACK_LABEL="address-feedback-$N"

  PR_REVIEW_WT=""
  PR_FOLLOWUP_WT=""
  ADDR_FEEDBACK_WT=""

  # Single porcelain pass via process substitution (not a pipe) so counters and
  # the WT variables set inside the loop survive past it — a pipe would run the
  # loop in a subshell and silently drop every assignment on exit.
  while IFS= read -r line; do
    case "$line" in
      "worktree "*)
        cur_wt=${line#worktree }
        base=${cur_wt##*/}
        case "$base" in
          "$PR_REVIEW_LABEL") PR_REVIEW_WT="$cur_wt" ;;
          "$PR_FOLLOWUP_LABEL") PR_FOLLOWUP_WT="$cur_wt" ;;
          "$ADDR_FEEDBACK_LABEL") ADDR_FEEDBACK_WT="$cur_wt" ;;
        esac
        ;;
    esac
  done < <(git worktree list --porcelain)

  # Bare-N /tmp fallback paths (rimba-absent convention, per workflow-pr-review
  # and workflow-pr-review-followup Step 2): the worktree is checked out
  # --detach, so no `branch refs/heads/...` line exists to match in porcelain,
  # AND its basename is bare "<N>" / "<N>-followup", not the task label — so
  # the scan above cannot find it. Check the known literal paths directly.
  if [ -z "$PR_REVIEW_WT" ] && [ -d "/tmp/swe-workbench-pr-review/$N" ]; then
    PR_REVIEW_WT="/tmp/swe-workbench-pr-review/$N"
  fi
  if [ -z "$PR_FOLLOWUP_WT" ] && [ -d "/tmp/swe-workbench-pr-review/$N-followup" ]; then
    PR_FOLLOWUP_WT="/tmp/swe-workbench-pr-review/$N-followup"
  fi

  reap_one_worktree() {
    local label="$1" path="$2" delete_branch="$3"
    [ -n "$path" ] || return 0

    if [ -n "$RIMBA" ] && "$RIMBA" remove "$label" --force >/dev/null 2>&1; then
      :
    else
      git worktree remove --force "$path" >/dev/null 2>&1 || true
      if [ "$delete_branch" = "1" ]; then
        git branch -D "$label" >/dev/null 2>&1 || true
      fi
      if [ -d "$path" ]; then
        "$RUNTIME_DIR/clean-ephemeral.sh" "$path" >/dev/null 2>&1 || true
      fi
    fi

    [ -d "$path" ] || SWEPT_WORKTREES=$((SWEPT_WORKTREES + 1))
  }

  # Reviewer-flow worktrees: worktree + branch both reaped (throwaway detached
  # review copies). address-feedback: worktree only — never `git branch -D` it,
  # its branch may be the PR's real head branch.
  reap_one_worktree "$PR_REVIEW_LABEL" "$PR_REVIEW_WT" 1
  reap_one_worktree "$PR_FOLLOWUP_LABEL" "$PR_FOLLOWUP_WT" 1
  reap_one_worktree "$ADDR_FEEDBACK_LABEL" "$ADDR_FEEDBACK_WT" 0
fi

RESIDUAL_NONE=1
if [ "$SWEPT_WORKTREES" -gt 0 ] || [ "$SWEPT_STATE_FILES" -gt 0 ]; then
  RESIDUAL_NONE=0
fi

printf 'SWEPT_WORKTREES=%s\nSWEPT_STATE_FILES=%s\nRESIDUAL_NONE=%s\n' \
  "$SWEPT_WORKTREES" "$SWEPT_STATE_FILES" "$RESIDUAL_NONE"
