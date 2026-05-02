#!/usr/bin/env bash
set -euo pipefail

# ── Preflight ────────────────────────────────────────────────

BUMP="${1:-}"
if [[ ! "$BUMP" =~ ^(patch|minor|major)$ ]]; then
  echo "Usage: $0 <patch|minor|major>" >&2
  exit 1
fi

if ! gh auth status &>/dev/null; then
  echo "Error: gh CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

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
    git checkout main
    ;;
  *)
    echo "Error: must run from main or a 'chore/bump-v*' resume branch (currently on '${CURRENT_BRANCH}')." >&2
    exit 1
    ;;
esac

git fetch origin
git pull --ff-only origin main

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

PLUGIN_JSON=".claude-plugin/plugin.json"
MKT_JSON=".claude-plugin/marketplace.json"

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

ON_BRANCH_PLUGIN_VERSION=$(jq -r .version "$PLUGIN_JSON")
ON_BRANCH_MKT_VERSION=$(jq -r '.plugins[0].version' "$MKT_JSON")
COMMITTED=0

if [[ "$ON_BRANCH_PLUGIN_VERSION" == "$NEXT" && "$ON_BRANCH_MKT_VERSION" == "$NEXT" ]]; then
  echo "plugin.json and marketplace.json already at ${NEXT} — skipping bump commit."
else
  TMP_PLUGIN=$(mktemp)
  TMP_MKT=$(mktemp)
  jq --arg v "$NEXT" '.version = $v' "$PLUGIN_JSON" > "$TMP_PLUGIN" && mv "$TMP_PLUGIN" "$PLUGIN_JSON"
  jq --arg v "$NEXT" '.plugins[0].version = $v' "$MKT_JSON" > "$TMP_MKT" && mv "$TMP_MKT" "$MKT_JSON"
  git add "$PLUGIN_JSON" "$MKT_JSON"
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
  git push --force-with-lease -u origin "$BRANCH"
elif [[ -z "$REMOTE_BRANCH_SHA" ]] || [[ "$LOCAL_BRANCH_SHA" != "$REMOTE_BRANCH_SHA" ]]; then
  git push -u origin "$BRANCH"
else
  echo "Remote branch already up to date — skipping push."
fi

# ── PR (reuse if open, create otherwise) ─────────────────────

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

  while true; do
    if [[ $ELAPSED -ge $TIMEOUT ]]; then
      echo "Error: timed out waiting for CI on PR #${PR_NUM} after $((TIMEOUT / 60)) minutes." >&2
      echo "Check status at: ${PR_URL}" >&2
      echo "Once CI passes, manually merge and tag with:" >&2
      echo "  gh pr merge --squash --delete-branch ${PR_NUM}" >&2
      echo "  git checkout main && git pull --ff-only && git tag -a ${TAG} -m 'Release ${TAG}' && git push origin ${TAG}" >&2
      exit 1
    fi

    PENDING=$(gh pr checks "$PR_NUM" --json state \
      --jq '[.[] | select(.state == "PENDING" or .state == "IN_PROGRESS" or .state == "QUEUED" or .state == "WAITING")] | length' 2>/dev/null || echo "0")

    if [[ "$PENDING" -eq 0 ]]; then
      FAILED=$(gh pr checks "$PR_NUM" --json conclusion \
        --jq '[.[] | select(.conclusion == "FAILURE" or .conclusion == "CANCELLED" or .conclusion == "TIMED_OUT")] | length' 2>/dev/null || echo "0")

      if [[ "$FAILED" -gt 0 ]]; then
        echo "Error: ${FAILED} CI check(s) failed on PR #${PR_NUM}." >&2
        echo "Fix the failures at: ${PR_URL}" >&2
        echo "Once CI passes, manually merge and tag with:" >&2
        echo "  gh pr merge --squash --delete-branch ${PR_NUM}" >&2
        echo "  git checkout main && git pull --ff-only && git tag -a ${TAG} -m 'Release ${TAG}' && git push origin ${TAG}" >&2
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

git checkout main
git pull --ff-only origin main

MERGE_SHA=$(gh pr view "$PR_NUM" --json mergeCommit -q '.mergeCommit.oid')
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
  REMOTE_TAG_COMMIT=$(echo "$REMOTE_TAG_INFO" | grep '\^{}' | awk '{print $1}')
  [[ -z "$REMOTE_TAG_COMMIT" ]] && REMOTE_TAG_COMMIT=$(echo "$REMOTE_TAG_INFO" | awk '{print $1}' | head -1)
  if [[ -n "$REMOTE_TAG_COMMIT" && "$REMOTE_TAG_COMMIT" != "$MERGE_SHA" ]]; then
    echo "Error: remote tag ${TAG} exists but points to ${REMOTE_TAG_COMMIT}, not merge commit ${MERGE_SHA}." >&2
    echo "Inspect and delete the stale tag before re-running: git push origin :refs/tags/${TAG}" >&2
    exit 1
  fi
  echo "Tag ${TAG} already exists on origin — skipping."
elif git rev-parse -q --verify "${TAG}^{tag}" >/dev/null 2>&1; then
  echo "Tag ${TAG} exists locally — pushing to origin."
  git push origin "$TAG"
else
  git tag -a "$TAG" -m "Release ${TAG}"
  git push origin "$TAG"
fi

# Clean up local release branch (remote already deleted by --delete-branch)
git branch -d "$BRANCH" 2>/dev/null || true

echo ""
echo "Done!"
echo "  PR:       ${PR_URL}"
echo "  Tag:      ${TAG}"
echo "  Release:  https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/tag/${TAG}"
