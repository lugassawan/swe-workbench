#!/usr/bin/env bash
# Refreshes the remote-tracking ref for one branch before any merge-base
# comparison — a sync decision is only as fresh as the ref it reads.
# Reports whether the ref moved.
# Usage: fetch-latest.sh <default-branch>
# Stdout contract: DEFAULT_BRANCH=<name>                (%q-quoted)
#                  FETCH_RESULT=updated|unchanged
#                  OLD_REF=<sha>                        (%q-quoted; empty when
#                                                       no prior tracking ref)
#                  NEW_REF=<sha>                        (%q-quoted)
# Exit 0 on a successful fetch (updated or unchanged); non-zero when the
# fetch itself fails (git's stderr passes through; no contract lines are
# emitted, so the caller has nothing actionable to eval).
set -euo pipefail

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || { echo "fetch-latest: not inside a git work tree" >&2; exit 1; }

BRANCH="${1:?Usage: fetch-latest.sh <default-branch>}"

OLD_REF=$(git rev-parse -q --verify "refs/remotes/origin/$BRANCH" 2>/dev/null || true)

# Explicit refspec — the tracking-ref update is guaranteed, not left to
# opportunistic refspec matching.
if ! git fetch origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"; then
  echo "fetch-latest: git fetch origin $BRANCH failed" >&2
  exit 1
fi

NEW_REF=$(git rev-parse -q --verify "refs/remotes/origin/$BRANCH" 2>/dev/null) || {
  echo "fetch-latest: refs/remotes/origin/$BRANCH missing after fetch" >&2
  exit 1
}

if [ -n "$OLD_REF" ] && [ "$OLD_REF" = "$NEW_REF" ]; then
  FETCH_RESULT=unchanged
else
  FETCH_RESULT=updated
fi

# %q-quote the string fields — branch names may legally contain shell
# metacharacters, and this output is eval'd by the caller.
printf 'DEFAULT_BRANCH=%q\n' "$BRANCH"
printf 'FETCH_RESULT=%s\n' "$FETCH_RESULT"
printf 'OLD_REF=%q\n' "$OLD_REF"
printf 'NEW_REF=%q\n' "$NEW_REF"
