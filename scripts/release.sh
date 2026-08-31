#!/usr/bin/env bash
set -euo pipefail

# ── Preflight ────────────────────────────────────────────────

RESUME_TAG=""
if [[ "${1:-}" == "--resume" ]]; then
  RESUME_TAG="${2:-}"
  if [[ ! "$RESUME_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Usage: $0 <patch|minor|major>" >&2
    echo "       $0 --resume vX.Y.Z   (finish a merged-but-untagged release)" >&2
    exit 1
  fi
else
  BUMP="${1:-}"
  if [[ ! "$BUMP" =~ ^(patch|minor|major)$ ]]; then
    echo "Usage: $0 <patch|minor|major>" >&2
    echo "       $0 --resume vX.Y.Z   (finish a merged-but-untagged release)" >&2
    exit 1
  fi
fi

if ! gh auth status &>/dev/null; then
  echo "Error: gh CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

# Pin gh to the same remote git uses everywhere else in this script.
# Avoids "No default remote repository has been set" on multi-remote clones
# (e.g. when `gh repo fork` has added sibling remotes).
ORIGIN_URL=$(git remote get-url origin 2>/dev/null || true)
if [[ -z "$ORIGIN_URL" ]]; then
  echo "Error: 'origin' remote is not configured." >&2
  exit 1
fi
# Normalise SSH (git@github.com:owner/repo[.git]) and HTTPS
# (https://github.com/owner/repo[.git]) into owner/repo.
GH_REPO=$(printf '%s\n' "$ORIGIN_URL" \
  | sed -E 's#^git@github\.com:#https://github.com/#' \
  | sed -E 's#^https://github\.com/##; s#\.git$##')
if [[ ! "$GH_REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "Error: could not derive owner/repo from origin URL '${ORIGIN_URL}'." >&2
  exit 1
fi
export GH_REPO

if ! jq --version &>/dev/null; then
  echo "Error: jq is required. Install with: brew install jq" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree is dirty. Commit or stash your changes first." >&2
  exit 1
fi

# Land on main — auto-recover from a prior bump branch left by a failed run
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
case "$CURRENT_BRANCH" in
  main) ;;
  chore/bump-v*)
    echo "Detected in-progress release branch '${CURRENT_BRANCH}'. Switching to main."
    if ! git checkout main; then
      echo "Error: could not switch to main (checked out in another worktree?)." >&2
      echo "  Remedy: cd to the main worktree, switch off main, then re-run this script." >&2
      exit 1
    fi
    ;;
  *)
    echo "Error: must run from main or a 'chore/bump-v*' resume branch (currently on '${CURRENT_BRANCH}')." >&2
    exit 1
    ;;
esac

# ── Transport retry helper ─────────────────────────────
# One-shot git transport calls abort the whole release on a transient SSH
# reset. Wrap them with the same bounded-retry contract as the CI-wait loop
# below: classify (any non-zero exit = retryable transient), cap attempts,
# sleep between attempts. Every wrapped command is safe to re-run — fetch
# and ff-only pulls are read-only syncs, and pushes are idempotent ref
# updates the remote rejects on mismatch.
retry_transport() {
  local max_attempts=$1 desc=$2
  shift 2
  local attempt=0
  while true; do
    if "$@"; then
      return 0
    fi
    attempt=$((attempt + 1))
    if [[ "$attempt" -ge "$max_attempts" ]]; then
      echo "Error: ${desc} failed after ${attempt} attempts (transient failure cap reached)." >&2
      echo "  Re-run this script — it resumes the unfinished release." >&2
      return 1
    fi
    echo "[$(date '+%H:%M:%S')] ${desc} transient failure (attempt ${attempt}/${max_attempts}); retrying in 10s..." >&2
    sleep 10
  done
}

retry_transport 5 "git fetch origin" git fetch origin
retry_transport 5 "git pull" git pull --ff-only origin main

# ── Resume an unfinished release ─────────────────────────────
# A bump PR can merge and then lose its tag publication to a transport
# failure. GitHub is the single source of truth for reconstruction — no local
# checkpoint: headRefName survives branch deletion, mergeCommit pins the SHA,
# and remote tag presence decides what is left to do. Fails closed on any
# unverifiable field; never tags a commit the remote state does not prove.
resume_release() {
  local tag=$1
  local ver=${tag#v}
  local branch="chore/bump-${tag}"

  echo "Resuming release ${tag}..."

  local pr_json
  pr_json=$(retry_transport 5 "gh pr list (${branch})" \
    gh pr list --state merged --limit 20 \
      --json number,headRefName,mergeCommit \
      --jq "[.[] | select(.headRefName == \"${branch}\")][0]") || return 1
  if [[ -z "$pr_json" || "$pr_json" == "null" ]]; then
    echo "Error: no merged PR found for branch '${branch}' — cannot resume ${tag}." >&2
    echo "  Inspect: https://github.com/${GH_REPO}/pulls?q=is%3Apr+is%3Amerged+head%3A${branch}" >&2
    return 1
  fi

  local pr_num merge_sha
  pr_num=$(printf '%s' "$pr_json" | jq -r '.number')
  merge_sha=$(printf '%s' "$pr_json" | jq -r '.mergeCommit.oid')
  if [[ -z "$merge_sha" || "$merge_sha" == "null" ]]; then
    echo "Error: GitHub returned no merge commit for the '${branch}' PR." >&2
    return 1
  fi

  # The merge SHA must be reachable from origin/main — never tag an
  # unmerged or reverted commit.
  if ! git merge-base --is-ancestor "$merge_sha" origin/main; then
    echo "Error: merge SHA ${merge_sha} of PR #${pr_num} is not reachable from origin/main." >&2
    echo "  Was the release reverted? Inspect before resuming." >&2
    return 1
  fi

  # Every declared manifest at the merge SHA must carry the release version
  # (mirrors the publication gate in .github/workflows/release.yml).
  while IFS=$'\t' read -r path field; do
    local at_sha
    at_sha=$(git show "${merge_sha}:${path}" | jq -r "$field")
    if [[ "$at_sha" != "$ver" ]]; then
      echo "Error: ${path} at ${merge_sha} reports '${at_sha}', expected '${ver}'." >&2
      return 1
    fi
  done < <(jq -r '.files[] | [.path, .field] | @tsv' .version-bump.json)

  local remote_tag remote_tag_commit
  remote_tag=$(retry_transport 5 "tag lookup ${tag}" \
    git ls-remote --tags origin "refs/tags/${tag}" "refs/tags/${tag}^{}") || return 1
  # || true: grep exits 1 on no-match; pipefail would otherwise abort here.
  remote_tag_commit=$(printf '%s' "$remote_tag" | grep '\^{}' | awk '{print $1}' || true)
  [[ -z "$remote_tag_commit" ]] && remote_tag_commit=$(printf '%s' "$remote_tag" | awk '{print $1}' | head -1)
  if [[ -n "$remote_tag_commit" ]]; then
    if [[ "$remote_tag_commit" != "$merge_sha" ]]; then
      echo "Error: remote tag ${tag} points to ${remote_tag_commit}, not merge commit ${merge_sha}." >&2
      echo "  Inspect and delete the stale tag before re-running: git push origin :refs/tags/${tag}" >&2
      return 1
    fi
    echo "Tag ${tag} already published at ${merge_sha} — nothing to do."
    echo ""
    echo "Resumed release complete!"
    echo "  PR:       https://github.com/${GH_REPO}/pull/${pr_num}"
    echo "  Tag:      ${tag}"
    echo "  Release:  https://github.com/${GH_REPO}/releases/tag/${tag}"
    return 0
  fi

  # --no-verify is safe ONLY here: the tuple above was verified against
  # GitHub, and the PR's CI ran green on exactly this tree (a squash merge
  # preserves the branch-head tree), so the pre-push hook would re-run
  # validation that already passed. Fresh releases never skip the hook.
  if ! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null 2>&1; then
    git tag -a "$tag" -m "Release ${tag}" "$merge_sha"
  elif [[ "$(git rev-parse "${tag}^{commit}")" == "$merge_sha" ]]; then
    echo "Tag ${tag} exists locally at ${merge_sha} — pushing."
  else
    echo "Error: local tag ${tag} points to $(git rev-parse "${tag}^{commit}"), not ${merge_sha}." >&2
    echo "  Delete it before re-running: git tag -d ${tag}" >&2
    return 1
  fi
  retry_transport 5 "tag push" git push --no-verify origin "$tag"

  git branch -D "$branch" 2>/dev/null || true

  echo ""
  echo "Resumed release complete!"
  echo "  PR:       https://github.com/${GH_REPO}/pull/${pr_num}"
  echo "  Tag:      ${tag}"
  echo "  Release:  https://github.com/${GH_REPO}/releases/tag/${tag}"
  echo "  Re-run:   $0 <patch|minor|major> to start the next release"
  return 0
}

if [[ -n "$RESUME_TAG" ]]; then
  resume_release "$RESUME_TAG"
  exit 0
fi

# discover_untagged_releases: emit "<tag>\t<pr>\t<merge-sha>" per merged bump
# PR whose tag is absent from origin. headRefName is the primary key — it is
# machine-generated and survives branch deletion. A tag deleted manually is
# indistinguishable from an unpublished one; deletion is not an unpublish
# intent this script can honor.
discover_untagged_releases() {
  local merged_prs ver num sha tag_out
  merged_prs=$(retry_transport 5 "gh pr list" \
    gh pr list --state merged --limit 20 \
      --json number,headRefName,mergeCommit \
      --jq '.[] | select(.headRefName | test("^chore/bump-v[0-9]+[.][0-9]+[.][0-9]+$")) | select(.mergeCommit.oid != null and .mergeCommit.oid != "") | [(.headRefName | sub("^chore/bump-"; "")), (.number | tostring), .mergeCommit.oid] | @tsv') || return 1
  while IFS=$'\t' read -r ver num sha; do
    [[ -n "$ver" ]] || continue
    tag_out=$(retry_transport 5 "tag lookup ${ver}" \
      git ls-remote --tags origin "refs/tags/${ver}") || return 1
    if [[ -z "$tag_out" ]]; then
      printf '%s\t%s\t%s\n' "$ver" "$num" "$sha"
    fi
  done <<<"$merged_prs"
}

# ── Resume unfinished releases (before computing a new version) ─
# A rerun must finish a stranded release before deriving the next version —
# otherwise it would compute NEXT from the already-bumped manifest and fork
# a new release on top of an unpublished one (issue #695).
UNTAGGED=$(discover_untagged_releases) || {
  echo "Error: could not query GitHub for unfinished releases." >&2
  exit 1
}
UNTAGGED_COUNT=0
if [[ -n "$UNTAGGED" ]]; then
  UNTAGGED_COUNT=$(printf '%s\n' "$UNTAGGED" | grep -c .)
fi
if [[ "$UNTAGGED_COUNT" -ge 2 ]]; then
  echo "Error: multiple merged-but-untagged releases found — refusing to guess." >&2
  printf '%s\n' "$UNTAGGED" | while IFS=$'\t' read -r ver num sha; do
    echo "  ${ver}  PR #${num}  ${sha}" >&2
  done
  echo "Finish one explicitly with: $0 --resume vX.Y.Z" >&2
  exit 1
elif [[ "$UNTAGGED_COUNT" -eq 1 ]]; then
  RESUME_TAG=$(printf '%s\n' "$UNTAGGED" | head -1 | cut -f1)
  echo "Found unfinished release ${RESUME_TAG} (merged PR, missing tag) — resuming before starting a new release."
  resume_release "$RESUME_TAG"
  exit 0
fi
# No unfinished releases — fall through to a fresh release.

# ── Compute next version ─────────────────────────────────────

CURRENT=$(jq -r .version .claude-plugin/plugin.json)
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

NEXT="${MAJOR}.${MINOR}.${PATCH}"
TAG="v${NEXT}"
BRANCH="chore/bump-${TAG}"

echo "Target: ${CURRENT} → ${NEXT} (${TAG}) on ${BRANCH}"

# ── Branch (resume-aware) ────────────────────────────────────

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  echo "Local branch ${BRANCH} exists — reusing."
  git checkout "$BRANCH"
elif git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  echo "Remote branch ${BRANCH} exists — checking out tracking copy."
  git checkout -b "$BRANCH" "origin/${BRANCH}"
else
  git checkout -b "$BRANCH" main
fi

# ── Resync onto main if needed ───────────────────────────────
# --is-ancestor A B: returns true when A is an ancestor of B (B contains A).
# We want to rebase when $BRANCH is NOT already an ancestor of origin/main,
# i.e. when origin/main has moved past where $BRANCH branched off.

REBASED=0
if ! git merge-base --is-ancestor "$BRANCH" origin/main 2>/dev/null; then
  echo "Branch is behind origin/main — rebasing."
  if ! git rebase origin/main; then
    git rebase --abort 2>/dev/null || true
    echo "Error: rebase onto origin/main conflicted. Resolve by hand and re-run." >&2
    exit 1
  fi
  REBASED=1
fi

# ── Bump commit (only if files don't already match) ──────────
# N-way over every file declared in .version-bump.json, not hardcoded to plugin/marketplace —
# scripts/bump-version.sh is the single source of truth for which files carry the version.

DECLARED_PATHS=()
ALREADY_CORRECT=1
while IFS=$'\t' read -r path field; do
  DECLARED_PATHS+=("$path")
  VER=$(jq -r "$field" "$path")
  [[ "$VER" == "$NEXT" ]] || ALREADY_CORRECT=0
done < <(jq -r '.files[] | [.path, .field] | @tsv' .version-bump.json)

COMMITTED=0

if [[ "$ALREADY_CORRECT" -eq 1 ]]; then
  echo "All declared manifests already at ${NEXT} — skipping bump commit."
else
  ./scripts/bump-version.sh "$NEXT"
  git add "${DECLARED_PATHS[@]}"
  git commit -m "[chore] Bump version to ${NEXT}"
  COMMITTED=1
fi

# ── Push ─────────────────────────────────────────────────────
# Use --force-with-lease when rebased or when a new commit was added on top
# of an already-existing remote branch (normal push would be rejected as
# non-fast-forward if remote has the pre-commit SHA).

REMOTE_BRANCH_SHA=$(git ls-remote origin "refs/heads/${BRANCH}" | awk '{print $1}')
LOCAL_BRANCH_SHA=$(git rev-parse "$BRANCH")

if [[ "$REBASED" -eq 1 ]] || [[ "$COMMITTED" -eq 1 && -n "$REMOTE_BRANCH_SHA" ]]; then
  retry_transport 5 "branch push" git push --force-with-lease -u origin "$BRANCH"
elif [[ -z "$REMOTE_BRANCH_SHA" ]] || [[ "$LOCAL_BRANCH_SHA" != "$REMOTE_BRANCH_SHA" ]]; then
  retry_transport 5 "branch push" git push -u origin "$BRANCH"
else
  echo "Remote branch already up to date — skipping push."
fi

# ── PR (reuse if open, create otherwise) ─────────────────────

# EXISTING_PR resolves to the literal string "null" via two independent paths:
#   1. gh succeeds but finds no open PRs → `--jq '.[0]'` on an empty array emits "null"
#   2. gh itself fails (auth error, network, etc.) → `|| echo "null"` fires
# The `!= "null"` guard below catches both; do not simplify this without preserving both paths.
EXISTING_PR=$(gh pr list --head "$BRANCH" --base main --state open --json number,url --jq '.[0]' 2>/dev/null || echo "null")
if [[ -n "$EXISTING_PR" && "$EXISTING_PR" != "null" ]]; then
  PR_NUM=$(echo "$EXISTING_PR" | jq -r .number)
  PR_URL=$(echo "$EXISTING_PR" | jq -r .url)
  echo "Reusing existing PR #${PR_NUM}: ${PR_URL}"
else
  PR_URL=$(gh pr create \
    --base main \
    --head "$BRANCH" \
    --title "[chore] Bump version to ${NEXT}" \
    --body "$(cat <<PREOF
## Summary
- Bump version: \`${CURRENT}\` → \`${NEXT}\`
- Tag \`${TAG}\` will be pushed automatically once this merges, triggering \`.github/workflows/release.yml\` to publish a GitHub Release.

## Test Plan
- [x] CI (pr.yml) passes
- [x] Tag-triggered release workflow publishes \`${TAG}\`

N/A
PREOF
)" | tail -1)
  PR_NUM="${PR_URL##*/}"
  [[ "$PR_NUM" =~ ^[0-9]+$ ]] || { echo "Error: could not derive PR number from '${PR_URL}'" >&2; exit 1; }
  echo "PR created: ${PR_URL}"
fi

# ── CI + merge (skip if already merged) ──────────────────────

PR_STATE=$(gh pr view "$PR_NUM" --json state -q .state 2>/dev/null || echo "OPEN")
if [[ "$PR_STATE" == "MERGED" ]]; then
  echo "PR #${PR_NUM} already merged — skipping CI/merge."
else
  echo "Waiting for CI checks on PR #${PR_NUM}..."

  TIMEOUT=1200
  ELAPSED=0
  HEARTBEAT=60
  LAST_HEARTBEAT=0
  MAX_TRANSIENT=10
  TRANSIENT_COUNT=0

  while true; do
    TOTAL=0; PENDING=0; FAILED=0

    if [[ $ELAPSED -ge $TIMEOUT ]]; then
      echo "Error: timed out waiting for CI on PR #${PR_NUM} after $((TIMEOUT / 60)) minutes." >&2
      echo "Check status at: ${PR_URL}" >&2
      echo "Once CI passes, recover with:" >&2
      echo "  gh pr merge --squash --delete-branch ${PR_NUM}" >&2
      echo "  $0 --resume ${TAG}" >&2
      exit 1
    fi

    set +e
    CHECKS_JSON=$(gh pr checks "$PR_NUM" --json bucket 2>/dev/null)
    CHECKS_RC=$?
    set -e

    if [[ $CHECKS_RC -ne 0 && $CHECKS_RC -ne 8 ]]; then
      TRANSIENT_COUNT=$((TRANSIENT_COUNT + 1))
      if [[ $TRANSIENT_COUNT -ge $MAX_TRANSIENT ]]; then
        echo "Error: gh pr checks failed ${TRANSIENT_COUNT} times in a row (transient failure cap reached)." >&2
        echo "Check status at: ${PR_URL}" >&2
        echo "Once CI passes, recover with:" >&2
        echo "  gh pr merge --squash --delete-branch ${PR_NUM}" >&2
        echo "  $0 --resume ${TAG}" >&2
        exit 1
      fi
      echo "[$(date '+%H:%M:%S')] gh pr checks transient failure (rc=${CHECKS_RC}, attempt ${TRANSIENT_COUNT}/${MAX_TRANSIENT}); retrying in 10s..."
      sleep 10
      ELAPSED=$((ELAPSED + 10))
      continue
    fi

    if [[ $CHECKS_RC -eq 8 && -z "$CHECKS_JSON" ]]; then
      TRANSIENT_COUNT=$((TRANSIENT_COUNT + 1))
      if [[ $TRANSIENT_COUNT -ge $MAX_TRANSIENT ]]; then
        echo "Error: gh pr checks failed ${TRANSIENT_COUNT} times in a row (transient failure cap reached)." >&2
        echo "Check status at: ${PR_URL}" >&2
        echo "Once CI passes, recover with:" >&2
        echo "  gh pr merge --squash --delete-branch ${PR_NUM}" >&2
        echo "  $0 --resume ${TAG}" >&2
        exit 1
      fi
      echo "[$(date '+%H:%M:%S')] gh pr checks rc=8 but no output (attempt ${TRANSIENT_COUNT}/${MAX_TRANSIENT}); retrying in 10s..."
      sleep 10
      ELAPSED=$((ELAPSED + 10))
      continue
    fi

    TRANSIENT_COUNT=0

    TOTAL=$(printf '%s' "${CHECKS_JSON:-[]}" | jq 'length')
    PENDING=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.bucket == "pending")] | length')
    FAILED=$(printf '%s' "${CHECKS_JSON:-[]}" | jq '[.[] | select(.bucket == "fail" or .bucket == "cancel")] | length')

    if [[ "$TOTAL" -eq 0 ]]; then
      : # No checks registered yet — treat as pending and continue polling
    elif [[ "$PENDING" -eq 0 ]]; then
      if [[ "$FAILED" -gt 0 ]]; then
        echo "Error: ${FAILED} CI check(s) failed on PR #${PR_NUM}." >&2
        echo "Fix the failures at: ${PR_URL}" >&2
        echo "Once CI passes, recover with:" >&2
        echo "  gh pr merge --squash --delete-branch ${PR_NUM}" >&2
        echo "  $0 --resume ${TAG}" >&2
        exit 1
      fi

      echo "All CI checks passed. Waiting for branch-protection mergeability..."
      MERGE_TIMEOUT=120
      MERGE_ELAPSED=0
      while true; do
        S=$(gh pr view "$PR_NUM" --json mergeStateStatus -q .mergeStateStatus 2>/dev/null || echo UNKNOWN)
        case "$S" in
          CLEAN|HAS_HOOKS|UNSTABLE) break ;;
          BEHIND)
            # Requires rebase — polling won't resolve this
            echo "Error: PR #${PR_NUM} is behind origin/main (new commits landed while CI ran)." >&2
            echo "Rebase the bump branch and re-run this script:" >&2
            echo "  git checkout ${BRANCH} && git rebase origin/main && git push --force-with-lease" >&2
            exit 1
            ;;
          BLOCKED|UNKNOWN)
            if [[ $MERGE_ELAPSED -ge $MERGE_TIMEOUT ]]; then
              echo "Error: PR #${PR_NUM} not mergeable after ${MERGE_TIMEOUT}s (state: ${S}). Inspect at ${PR_URL}." >&2
              exit 1
            fi
            sleep 5; MERGE_ELAPSED=$((MERGE_ELAPSED + 5))
            ;;
          DIRTY|DRAFT)
            echo "Error: PR #${PR_NUM} cannot be merged (state: ${S})." >&2
            exit 1
            ;;
          *)
            echo "Error: unexpected mergeStateStatus '${S}'." >&2
            exit 1
            ;;
        esac
      done

      echo "Merging PR #${PR_NUM}..."
      gh pr merge --squash --delete-branch "$PR_NUM"
      echo "PR #${PR_NUM} merged."
      break
    fi

    if [[ $((ELAPSED - LAST_HEARTBEAT)) -ge $HEARTBEAT ]]; then
      echo "[$(date '+%H:%M:%S')] CI still running... (${ELAPSED}s elapsed, ${PENDING} check(s) pending)"
      LAST_HEARTBEAT=$ELAPSED
    fi

    sleep 10
    ELAPSED=$((ELAPSED + 10))
  done
fi

# ── Sync main + verify merge SHA ─────────────────────────────

if ! git checkout main; then
  echo "Error: could not switch to main (checked out in another worktree?)." >&2
  echo "  Remedy: cd to the main worktree, switch off main, then re-run this script." >&2
  exit 1
fi
retry_transport 5 "git pull" git pull --ff-only origin main

MERGE_SHA=""
POLL_TIMEOUT=60
POLL_ELAPSED=0
while [[ $POLL_ELAPSED -lt $POLL_TIMEOUT ]]; do
  MERGE_SHA=$(gh pr view "$PR_NUM" --json mergeCommit -q '.mergeCommit.oid' 2>/dev/null || true)
  [[ -n "$MERGE_SHA" ]] && break
  echo "[$(date '+%H:%M:%S')] mergeCommit.oid not yet available (${POLL_ELAPSED}s elapsed); retrying..."
  sleep 3
  POLL_ELAPSED=$((POLL_ELAPSED + 3))
done

if [[ -z "$MERGE_SHA" ]]; then
  echo "Error: GitHub did not return mergeCommit.oid for PR #${PR_NUM} within ${POLL_TIMEOUT}s." >&2
  echo "PR is merged; tagging skipped. Re-run this script — it discovers the merged release and finishes it." >&2
  exit 1
fi

LOCAL_SHA=$(git rev-parse HEAD)

if [[ "$LOCAL_SHA" != "$MERGE_SHA" ]]; then
  echo "Error: local main HEAD (${LOCAL_SHA}) does not match merge commit (${MERGE_SHA})." >&2
  echo "Something unexpected was pushed to main. Aborting tag to avoid tagging wrong commit." >&2
  exit 1
fi

# ── Tag (skip if already pushed, error if wrong commit) ──────

if git ls-remote --tags --exit-code origin "$TAG" >/dev/null 2>&1; then
  # Verify the existing tag targets the expected merge commit
  REMOTE_TAG_INFO=$(git ls-remote --tags origin "refs/tags/${TAG}" "refs/tags/${TAG}^{}" 2>/dev/null || true)
  REMOTE_TAG_COMMIT=$(printf '%s' "$REMOTE_TAG_INFO" | grep '\^{}' | awk '{print $1}' || true)
  [[ -z "$REMOTE_TAG_COMMIT" ]] && REMOTE_TAG_COMMIT=$(echo "$REMOTE_TAG_INFO" | awk '{print $1}' | head -1)
  if [[ -n "$REMOTE_TAG_COMMIT" && "$REMOTE_TAG_COMMIT" != "$MERGE_SHA" ]]; then
    echo "Error: remote tag ${TAG} exists but points to ${REMOTE_TAG_COMMIT}, not merge commit ${MERGE_SHA}." >&2
    echo "Inspect and delete the stale tag before re-running: git push origin :refs/tags/${TAG}" >&2
    exit 1
  fi
  echo "Tag ${TAG} already exists on origin — skipping."
elif git rev-parse -q --verify "${TAG}^{tag}" >/dev/null 2>&1; then
  echo "Tag ${TAG} exists locally — pushing to origin."
  retry_transport 5 "tag push" git push origin "$TAG"
else
  git tag -a "$TAG" -m "Release ${TAG}"
  retry_transport 5 "tag push" git push origin "$TAG"
fi

# Clean up local release branch (remote already deleted by --delete-branch)
git branch -d "$BRANCH" 2>/dev/null || true

echo ""
echo "Done!"
echo "  PR:       ${PR_URL}"
echo "  Tag:      ${TAG}"
echo "  Release:  https://github.com/${GH_REPO}/releases/tag/${TAG}"
