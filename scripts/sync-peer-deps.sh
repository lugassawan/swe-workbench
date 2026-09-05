#!/usr/bin/env bash
set -euo pipefail

# Keeps the peerDependencies floor for @earendil-works/pi-coding-agent and pi-tui locked to
# the exact devDependencies pin — tests/test_pi_extension.py::test_package_json_values
# enforces this lockstep so a consumer can never sit on a floor whose tested behavior has
# since changed underneath it (see commit 0e34767). Dependabot only ever bumps the exact
# devDependencies pin, never peerDependencies (">=X <1" already satisfies the new pin, so its
# semver updater has no violation to fix), so this drifts on every pi-coding-agent/pi-tui
# bump unless synced explicitly — this script is that explicit sync, run by hand or by
# .github/workflows/dependabot-peer-sync.yml.
#
# Usage:
#   scripts/sync-peer-deps.sh --check   # fail if the floor is out of sync; make no changes
#   scripts/sync-peer-deps.sh           # rewrite package.json + package-lock.json in place
#
# Exit codes (distinguished so a caller like dependabot-peer-sync.yml can tell "there is
# actionable drift to fix" apart from "this script cannot proceed at all" — pi-coding-agent
# and pi-tui are bumped as two SEPARATE dependabot PRs, so the first of every such pair
# always hits the lockstep guard below; that must never be treated as syncable drift):
#   0 - already in sync (or, in apply mode, sync completed)
#   1 - actionable floor drift found (only in --check mode)
#   2 - hard error: cannot determine or apply the correct floor (missing jq, missing/
#       malformed devDependencies or peerDependencies keys, or the two packages' pins are
#       out of lockstep) — nothing was or could be synced

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG="${ROOT}/package.json"
LOCK="${ROOT}/package-lock.json"

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required." >&2
  exit 2
fi

PIN=$(jq -r '.devDependencies["@earendil-works/pi-coding-agent"]' "$PKG")
if [[ -z "$PIN" || "$PIN" == "null" ]]; then
  echo "Error: could not read devDependencies[\"@earendil-works/pi-coding-agent\"] from ${PKG}" >&2
  exit 2
fi

# pi-coding-agent and pi-tui are nested and published lockstep (see
# tests/test_pi_extension.py's tui_dev_pin == dev_pin assertion) — this script only derives
# the expected floor from one pin, so a partial bump that skips pi-tui must fail loudly here
# rather than silently syncing pi-tui's floor to a pin pi-tui never actually moved to. This is
# not a rare edge case: dependabot.yml has no `groups:` for npm, so pi-coding-agent and pi-tui
# bump as two separate PRs — every such pair's first PR lands in exactly this state.
TUI_PIN=$(jq -r '.devDependencies["@earendil-works/pi-tui"]' "$PKG")
if [[ "$TUI_PIN" != "$PIN" ]]; then
  echo "Error: devDependencies pins are out of lockstep — pi-coding-agent is ${PIN}, pi-tui is ${TUI_PIN}" >&2
  exit 2
fi

FLOOR=$(jq -e -r '.peerDependencies["@earendil-works/pi-coding-agent"] | split(" ")[0]' "$PKG") || {
  echo "Error: could not read peerDependencies[\"@earendil-works/pi-coding-agent\"] from ${PKG}" >&2
  exit 2
}
EXPECTED_FLOOR=">=${PIN}"

MODE="${1:-}"

if [[ "$FLOOR" == "$EXPECTED_FLOOR" ]]; then
  echo "peerDependencies floor already in sync with devDependencies pin (${PIN})."
  exit 0
fi

if [[ "$MODE" == "--check" ]]; then
  echo "::error::peerDependencies floor (${FLOOR}) is out of sync with the devDependencies pin (${PIN} -> expected floor ${EXPECTED_FLOOR}); run scripts/sync-peer-deps.sh" >&2
  exit 1
fi

# package-lock.json (lockfileVersion 3) mirrors the root manifest's peerDependencies under
# packages[""] — there is no legacy top-level "dependencies" block to also update.
_sync_json() {
  local file="$1" jq_filter="$2"
  local tmp
  tmp=$(mktemp)
  jq --arg range ">=${PIN} <1" "$jq_filter" "$file" > "$tmp"
  mv "$tmp" "$file"
}

_sync_json "$PKG" '
  .peerDependencies["@earendil-works/pi-coding-agent"] = $range
  | .peerDependencies["@earendil-works/pi-tui"] = $range
'

_sync_json "$LOCK" '
  .packages[""].peerDependencies["@earendil-works/pi-coding-agent"] = $range
  | .packages[""].peerDependencies["@earendil-works/pi-tui"] = $range
'

echo "Synced peerDependencies floor to >=${PIN} <1 in package.json and package-lock.json."
