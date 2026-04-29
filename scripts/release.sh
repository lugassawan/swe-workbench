#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# Preflight
# ──────────────────────────────────────────────

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

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "Error: must run from main, currently on '${CURRENT_BRANCH}'." >&2
  exit 1
fi

git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "Error: local main is not up to date with origin/main. Run: git pull --ff-only" >&2
  exit 1
fi

# ──────────────────────────────────────────────
# Compute next version
# ──────────────────────────────────────────────

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

echo "Bumping ${CURRENT} → ${NEXT} (${TAG})"

# ──────────────────────────────────────────────
# Branch + edit + commit
# ──────────────────────────────────────────────

git checkout -b "$BRANCH"

# Atomic writes via temp + mv to avoid half-written state on crash
PLUGIN_JSON=".claude-plugin/plugin.json"
MKT_JSON=".claude-plugin/marketplace.json"

TMP_PLUGIN=$(mktemp)
TMP_MKT=$(mktemp)

jq --arg v "$NEXT" '.version = $v' "$PLUGIN_JSON" > "$TMP_PLUGIN" && mv "$TMP_PLUGIN" "$PLUGIN_JSON"
jq --arg v "$NEXT" '.plugins[0].version = $v' "$MKT_JSON" > "$TMP_MKT" && mv "$TMP_MKT" "$MKT_JSON"

git add "$PLUGIN_JSON" "$MKT_JSON"
git commit -m "[chore] Bump version to ${NEXT}"

# ──────────────────────────────────────────────
# Push + PR
# ──────────────────────────────────────────────

git push -u origin "$BRANCH"

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
)")

echo "PR created: ${PR_URL}"

PR_NUM=$(echo "$PR_URL" | grep -oE '[0-9]+$')

# ──────────────────────────────────────────────
# Wait for CI checks, then merge explicitly
# ──────────────────────────────────────────────

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

  # Count checks still running
  PENDING=$(gh pr checks "$PR_NUM" --json state \
    --jq '[.[] | select(.state == "PENDING" or .state == "IN_PROGRESS" or .state == "QUEUED" or .state == "WAITING")] | length' 2>/dev/null || echo "0")

  if [[ "$PENDING" -eq 0 ]]; then
    # All checks finished — look for failures
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

    echo "All CI checks passed. Merging PR #${PR_NUM}..."
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

# ──────────────────────────────────────────────
# Tag and push
# ──────────────────────────────────────────────

git checkout main
git pull --ff-only origin main

MERGE_SHA=$(gh pr view "$PR_NUM" --json mergeCommit -q '.mergeCommit.oid')
LOCAL_SHA=$(git rev-parse HEAD)

if [[ "$LOCAL_SHA" != "$MERGE_SHA" ]]; then
  echo "Error: local main HEAD (${LOCAL_SHA}) does not match merge commit (${MERGE_SHA})." >&2
  echo "Something unexpected was pushed to main. Aborting tag to avoid tagging wrong commit." >&2
  exit 1
fi

git tag -a "$TAG" -m "Release ${TAG}"
git push origin "$TAG"

# Clean up local release branch (remote already deleted by --delete-branch)
git branch -d "$BRANCH" 2>/dev/null || true

echo ""
echo "Done!"
echo "  PR:       ${PR_URL}"
echo "  Tag:      ${TAG}"
echo "  Release:  https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/tag/${TAG}"
