#!/usr/bin/env bash
set -euo pipefail

# Keeps the peerDependencies range for @earendil-works/pi-coding-agent and pi-tui locked to
# the exact devDependencies pin — tests/test_pi_extension.py::test_package_json_values
# enforces this lockstep so a consumer can never sit on a floor whose tested behavior has
# since changed underneath it (see commit 0e34767). The range is ">=PIN <MAJOR+1": the floor
# is the pin itself and the ceiling is the next major above it, so a 0.x pin keeps "<1" and a
# 1.x pin gets "<2" rather than the unsatisfiable ">=1.0.3 <1". Dependabot only ever bumps
# the exact devDependencies pin, never peerDependencies (the old range already satisfies a
# new pin, so its semver updater has no violation to fix), so this drifts on every
# pi-coding-agent/pi-tui bump unless synced explicitly — this script is that explicit sync,
# run by hand or by .github/workflows/dependabot-peer-sync.yml.
#
# Usage:
#   scripts/sync-peer-deps.sh --check   # fail if any range is out of sync; make no changes
#   scripts/sync-peer-deps.sh           # rewrite package.json + package-lock.json in place
#
# Exit codes (distinguished so a caller like dependabot-peer-sync.yml can tell "there is
# actionable drift to fix" apart from "this script cannot proceed at all" — pi-coding-agent
# and pi-tui are bumped as two SEPARATE dependabot PRs, so the first of every such pair
# always hits the lockstep guard below; that must never be treated as syncable drift):
#   0 - already in sync (or, in apply mode, sync completed)
#   1 - actionable range drift found in any of the four sites — pi-coding-agent and pi-tui,
#       each in package.json and package-lock.json (only in --check mode)
#   2 - hard error: cannot determine or apply the correct range (missing jq, missing/
#       malformed devDependencies or peerDependencies keys, a pin that is not an exact
#       X.Y.Z, or the two packages' pins are out of lockstep) — nothing was or could be
#       synced

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
# the expected range from one pin, so a partial bump that skips pi-tui must fail loudly here
# rather than silently syncing pi-tui's range to a pin pi-tui never actually moved to. This is
# not a rare edge case: dependabot.yml has no `groups:` for npm, so pi-coding-agent and pi-tui
# bump as two separate PRs — every such pair's first PR lands in exactly this state.
TUI_PIN=$(jq -r '.devDependencies["@earendil-works/pi-tui"]' "$PKG")
if [[ "$TUI_PIN" != "$PIN" ]]; then
  echo "Error: devDependencies pins are out of lockstep — pi-coding-agent is ${PIN}, pi-tui is ${TUI_PIN}" >&2
  exit 2
fi

# Anything but a bare semver X.Y.Z (a ^/~ range, a prerelease tag, a leading-zero part that
# bash arithmetic would read as octal) would make the major-derived ceiling below wrong
# without any visible error.
if [[ ! "$PIN" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "Error: devDependencies pin must be an exact X.Y.Z version, got ${PIN}" >&2
  exit 2
fi

CURRENT_RANGE=$(jq -e -r '.peerDependencies["@earendil-works/pi-coding-agent"]' "$PKG") || {
  echo "Error: could not read peerDependencies[\"@earendil-works/pi-coding-agent\"] from ${PKG}" >&2
  exit 2
}

# The drift reads below run in a command substitution, where errexit is off — an unreadable
# lockfile would otherwise show up as "missing" drift (exit 1, actionable) instead of the
# hard error it is.
if ! jq -e '.packages[""]' "$LOCK" &>/dev/null; then
  echo "Error: could not read packages[\"\"] from ${LOCK}" >&2
  exit 2
fi
EXPECTED_CEILING="<$(( ${PIN%%.*} + 1 ))"
EXPECTED_RANGE=">=${PIN} ${EXPECTED_CEILING}"

MODE="${1:-}"

# Every site the apply step writes. pi-coding-agent's package.json entry was already required
# above; a missing pi-tui or lockfile entry reads as empty and so counts as drift.
_drift_sites() {
  local pkg_agent="$CURRENT_RANGE" pkg_tui lock_agent lock_tui
  pkg_tui=$(jq -r '.peerDependencies["@earendil-works/pi-tui"] // ""' "$PKG")
  lock_agent=$(jq -r '.packages[""].peerDependencies["@earendil-works/pi-coding-agent"] // ""' "$LOCK")
  lock_tui=$(jq -r '.packages[""].peerDependencies["@earendil-works/pi-tui"] // ""' "$LOCK")
  [[ "$pkg_agent" == "$EXPECTED_RANGE" ]] || echo "package.json pi-coding-agent (${pkg_agent:-missing})"
  [[ "$pkg_tui" == "$EXPECTED_RANGE" ]] || echo "package.json pi-tui (${pkg_tui:-missing})"
  [[ "$lock_agent" == "$EXPECTED_RANGE" ]] || echo "package-lock.json pi-coding-agent (${lock_agent:-missing})"
  [[ "$lock_tui" == "$EXPECTED_RANGE" ]] || echo "package-lock.json pi-tui (${lock_tui:-missing})"
}

DRIFT=$(_drift_sites)

if [[ -z "$DRIFT" ]]; then
  echo "peerDependencies already in sync with devDependencies pin (${PIN}): ${EXPECTED_RANGE}."
  exit 0
fi

if [[ "$MODE" == "--check" ]]; then
  echo "::error::peerDependencies out of sync with the devDependencies pin (${PIN} -> expected ${EXPECTED_RANGE}): ${DRIFT//$'\n'/, }; run scripts/sync-peer-deps.sh" >&2
  exit 1
fi

# A major crossing changes what the published range accepts; surface it so a reviewer sees
# the new ceiling without the script blocking the sync.
CURRENT_CEILING="none"
if [[ "$CURRENT_RANGE" =~ (\<[0-9]+)[[:space:]]*$ ]]; then
  CURRENT_CEILING="${BASH_REMATCH[1]}"
fi
if [[ "$CURRENT_CEILING" != "$EXPECTED_CEILING" ]]; then
  echo "::warning::peerDependencies ceiling changed from ${CURRENT_CEILING} to ${EXPECTED_CEILING} (pin ${PIN})"
fi

# package-lock.json (lockfileVersion 3) mirrors the root manifest's peerDependencies under
# packages[""] — there is no legacy top-level "dependencies" block to also update.
_sync_json() {
  local file="$1" jq_filter="$2"
  local tmp
  tmp=$(mktemp)
  jq --arg range "$EXPECTED_RANGE" "$jq_filter" "$file" > "$tmp"
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

echo "Synced peerDependencies to ${EXPECTED_RANGE} in package.json and package-lock.json."
