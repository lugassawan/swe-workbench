#!/usr/bin/env bash
# Anchors cwd to the main repo, syncs local main, and checks whether the
# rimba post-merge hook already cleaned up the given branch.
# Usage: sync-and-verify.sh <head_ref> [default_branch]
# Stdout contract: WORKTREE_GONE=0|1 <newline> HOOK_INTERRUPTED=0|1
# Exit non-zero only if $MAIN_REPO cannot be resolved.
set -euo pipefail

HEAD_REF="${1:?Usage: sync-and-verify.sh <head_ref> [default_branch]}"
DEFAULT_BRANCH="${2:-$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo main)}"

# Block A: derive $MAIN_REPO and anchor cwd
MAIN_REPO=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
[ -n "${MAIN_REPO:-}" ] || { echo "sync-and-verify: could not resolve main repo path — aborting" >&2; exit 1; }
cd "$MAIN_REPO"

# Resolve $HEAD_REF's own worktree (path + tracked-file count) up front, before
# the pull below can trigger the post-merge hook against it. Shared by the
# adaptive watchdog budget (Block B) and the subtree-wipe probe (Block D):
# `git ls-files` reads the index, which a plain `rm` inside the hook never
# touches, so the same count is valid as both "files to budget for" (read
# pre-pull) and "files that should still be there" (compared post-pull, in
# Block D) — race-stable and cheap even against tens of thousands of files.
# Use awk string comparison (-v) to avoid regex metachar injection from HEAD_REF.
HEAD_WT=$(git worktree list --porcelain \
  | awk -v ref="branch refs/heads/$HEAD_REF" '/^worktree /{p=$2} $0 == ref {print p; exit}')
HEAD_WT_FILES=0
if [ -n "${HEAD_WT:-}" ] && [ -d "$HEAD_WT" ]; then
  if _n=$(git -C "$HEAD_WT" ls-files 2>/dev/null | wc -l | tr -d ' '); then
    HEAD_WT_FILES=$_n
  fi
fi

# Block B: sync local default branch (best-effort — failure warns, does not abort)
# Backgrounded under an internal watchdog so an external tool-call kill can
# never hit this step uncontrolled: firing before that external timeout turns
# an unrecoverable process-tree kill into a controlled in-script exit that
# still runs Block D's detection. This does NOT prevent corruption — a kill
# can still land during the hook's rm — it makes it detectable and recoverable.
#
# TOTAL_CAP (570s) below is coupled to the Bash-tool-call timeout the caller
# (SKILL.md Step 3b) must pass when invoking this script (~600s). The internal
# watchdog MUST fire before that external timeout, or the external kill lands
# first and Block D never runs — the script cannot self-enforce this invariant;
# it is documented here AND in SKILL.md Step 3b.
if [ "${SYNC_TIMEOUT+set}" = "set" ]; then
  # Explicit override always wins — used by tests and manual overrides.
  # `${SYNC_TIMEOUT+set}` (presence), not `${SYNC_TIMEOUT:-}` (non-empty): the
  # latter treats SYNC_TIMEOUT="" the same as unset, silently routing an
  # explicit-but-empty override into the adaptive path below instead of the
  # invalid-input fallback the case guard already provides for "90s" etc.
  case "$SYNC_TIMEOUT" in
    ''|*[!0-9]*)
      echo "sync-and-verify: invalid SYNC_TIMEOUT='$SYNC_TIMEOUT' (must be a non-negative integer) — falling back to 90" >&2
      SYNC_TIMEOUT=90
      ;;
  esac
else
  # Split budget: PULL_BUDGET covers the network pull; HOOK_BUDGET scales with
  # how many tracked files the post-merge hook has to reap (K files/sec is an
  # empirical throughput estimate, not measured per-repo), so a 23k-file
  # monorepo worktree doesn't starve the hook of its cleanup window.
  PULL_BUDGET="${PULL_TIMEOUT:-90}"
  case "$PULL_BUDGET" in
    ''|*[!0-9]*)
      echo "sync-and-verify: invalid PULL_TIMEOUT='$PULL_BUDGET' (must be a non-negative integer) — falling back to 90" >&2
      PULL_BUDGET=90
      ;;
  esac
  K=50
  HOOK_CAP=480
  TOTAL_CAP=570
  # Known scope limit: HOOK_BUDGET only accounts for $HEAD_REF's own tracked
  # files. `rimba clean --merged --force` sweeps ALL currently-merged
  # worktrees in one invocation, so a bulk multi-PR cleanup round (this
  # script invoked once per merged PR, but the *first* pull's hook fires
  # against every already-merged worktree at once) can still starve the hook
  # even though this run's budget looks sufficient for $HEAD_REF alone.
  HOOK_BUDGET=$(( (HEAD_WT_FILES + K - 1) / K ))
  [ "$HOOK_BUDGET" -le "$HOOK_CAP" ] || HOOK_BUDGET=$HOOK_CAP
  _uncapped_total=$(( PULL_BUDGET + HOOK_BUDGET ))
  SYNC_TIMEOUT=$_uncapped_total
  [ "$SYNC_TIMEOUT" -le "$TOTAL_CAP" ] || SYNC_TIMEOUT=$TOTAL_CAP
  _capped_note=""
  [ "$_uncapped_total" -le "$TOTAL_CAP" ] || _capped_note=" — capped from ${_uncapped_total}s"
  echo "sync-and-verify: adaptive watchdog budget=${SYNC_TIMEOUT}s (pull=${PULL_BUDGET}s + hook=${HOOK_BUDGET}s for ${HEAD_WT_FILES} tracked files)${_capped_note}" >&2
fi
TIMED_OUT=0
set -m # give the backgrounded job its own process group
( git checkout "$DEFAULT_BRANCH" \
    && git pull --ff-only origin "$DEFAULT_BRANCH" ) >/dev/null 2>&1 &
job=$!
elapsed=0
while kill -0 "$job" 2>/dev/null; do
  if [ "$elapsed" -ge "$SYNC_TIMEOUT" ]; then
    kill -TERM -"$job" 2>/dev/null || true # negative PID = whole group: git + orphaned rimba hook child
    sleep 2
    kill -KILL -"$job" 2>/dev/null || true
    TIMED_OUT=1
    break
  fi
  sleep 1
  elapsed=$((elapsed + 1)) # NOT ((elapsed++)) — returns 1 (falsy) at 0, trips set -e
done
pull_rc=0
wait "$job" 2>/dev/null || pull_rc=$? # `wait; pull_rc=$?` on separate lines is unreachable under set -e
set +m

if [ "$TIMED_OUT" -eq 1 ]; then
  echo "sync-and-verify: internal timeout (${SYNC_TIMEOUT}s) killed the checkout/pull — $DEFAULT_BRANCH sync may be incomplete, verify manually" >&2
elif [ "$pull_rc" -ne 0 ]; then
  echo "sync-main: best-effort failed — reconcile $DEFAULT_BRANCH manually (run git pull to see the underlying error)" >&2
fi

# Block C: verification gate — check whether hook already cleaned up
# Use awk string comparison (-v) to avoid regex metachar injection from HEAD_REF
WORKTREE_FOUND=$(git worktree list --porcelain \
  | awk -v ref="branch refs/heads/$HEAD_REF" '$0 == ref {print 1; exit}')
if git rev-parse --verify "refs/heads/$HEAD_REF" >/dev/null 2>&1; then
  BRANCH_FOUND=1
else
  BRANCH_FOUND=
fi

WORKTREE_GONE=0
[ -z "${WORKTREE_FOUND:-}" ] && [ -z "${BRANCH_FOUND:-}" ] && WORKTREE_GONE=1

# Block D: partial-deletion probe — canonical state-based signal that the
# rimba post-merge hook (or a prior cleanup run) was interrupted mid-rm: a
# worktree still registered in .git but whose directory is gone from disk.
# State, not event: robust to external kills that also took down this script
# on a prior run, not just to a timeout caught by Block B on this run.
HOOK_INTERRUPTED=0
while IFS= read -r _line; do
  case "$_line" in
    "worktree "*) _wt=${_line#worktree }; [ -d "$_wt" ] || HOOK_INTERRUPTED=1 ;;
  esac
done < <(git worktree list --porcelain)

# Fix A (#532): targeted subtree-deletion probe. The loop above only catches a
# worktree whose *top-level* directory vanished. When the Block B watchdog
# kills the post-merge hook mid-rm, the worktree root can survive while a
# subtree of tracked files underneath it is wiped — the loop above sees
# `[ -d "$_wt" ]` succeed and HOOK_INTERRUPTED stays a false 0, and
# `git worktree prune` (the recovery advice below) is a no-op for this shape:
# prune only clears missing *directories*, never files missing inside a live
# one. Ratio, not "any deletion", so a worktree that's just legitimately dirty
# doesn't get flagged as interrupted.
SUBTREE_WIPED=0
SUBTREE_PROBE_FAILED=0
if [ -n "${HEAD_WT:-}" ] && [ -d "$HEAD_WT" ] && [ "${HEAD_WT_FILES:-0}" -gt 0 ]; then
  _dels=0
  if _d=$(git -C "$HEAD_WT" status --porcelain 2>/dev/null | awk '
      {
        x = substr($0, 1, 1); y = substr($0, 2, 1)
        if (x == "U" || y == "U") next        # unmerged (UU/UD/UA/AU/DU)
        if (x == "D" && y == "D") next        # unmerged: both deleted
        if (x == "A" && y == "A") next        # unmerged: both added
        if (x == "D" || y == "D") c++
      }
      END { print c + 0 }
    '); then
    _dels=$_d
  else
    # `git status` itself failed inside $HEAD_WT (e.g. its own .git pointer
    # file/admin metadata was among the files reaped before the kill landed).
    # Do NOT default to "0% deleted" here — that would silently report a
    # false-clean state for the exact interrupted-hook shape this probe
    # exists to catch. Flag as inconclusive-but-suspicious instead.
    SUBTREE_PROBE_FAILED=1
  fi
  if [ "$SUBTREE_PROBE_FAILED" -eq 1 ]; then
    HOOK_INTERRUPTED=1
  elif [ "$(( _dels * 100 / HEAD_WT_FILES ))" -ge 90 ]; then
    HOOK_INTERRUPTED=1
    SUBTREE_WIPED=1
  fi
fi

if [ "$HOOK_INTERRUPTED" -eq 1 ]; then
  if [ "$SUBTREE_PROBE_FAILED" -eq 1 ]; then
    echo "sync-and-verify: could not verify $HEAD_REF's worktree state ($HEAD_WT) — the deletion-ratio probe itself failed (git status errored), which can happen if the worktree's own admin metadata was reaped before a kill landed. Treating as a possible interrupted hook out of caution. Recover: inspect $HEAD_WT manually (e.g. 'git -C $HEAD_WT status') before assuming it's clean." >&2
  elif [ "$SUBTREE_WIPED" -eq 1 ]; then
    echo "sync-and-verify: partial worktree deletion detected — $HEAD_REF's worktree root ($HEAD_WT) is intact but its tracked files are gone (the post-merge hook was likely interrupted mid-cleanup). The directory still exists, so pruning stale worktree registrations will not help. Recover: run 'git -C $HEAD_WT restore .' to restore the missing files, or re-run 'rimba clean --merged --force' to finish removing the worktree." >&2
  elif [ "$TIMED_OUT" -eq 1 ]; then
    echo "sync-and-verify: internal timeout (${SYNC_TIMEOUT}s) interrupted the post-merge hook — partial worktree deletion detected. Recover: run 'git worktree prune' from the main repo, then delete the stale branch." >&2
  else
    echo "sync-and-verify: partial worktree deletion detected (a registered worktree is missing on disk — a prior cleanup was likely interrupted). Recover: run 'git worktree prune' from the main repo." >&2
  fi
fi

printf 'WORKTREE_GONE=%s\n' "$WORKTREE_GONE"
printf 'HOOK_INTERRUPTED=%s\n' "$HOOK_INTERRUPTED"
