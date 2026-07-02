#!/usr/bin/env bash
set -euo pipefail

# ── Usage ──────────────────────────────────────────────────────

CHECK=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --help|-h)
      echo "Usage: $0 [--check]"
      echo ""
      echo "  Regenerates tests/requirements.lock, tests/release-requirements.lock,"
      echo "  and tests/build-requirements.lock from their source files using"
      echo "  pip-compile --generate-hashes, targeting Python 3.12 (matching CI)."
      echo ""
      echo "  Without --check, this always performs a full --upgrade re-resolution,"
      echo "  so transitive pins may bump even if you only touched one source file."
      echo ""
      echo "  --check  Verify lockfiles are up-to-date (CI-friendly, exits 1 if drift)."
      exit 0
      ;;
    *)
      echo "Error: unknown argument '$arg'" >&2
      echo "Run '$0 --help' for usage." >&2
      exit 1
      ;;
  esac
done

# ── Preflight ──────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Prefer python3.12; fall back to python3 if it is already 3.12.x.
PYTHON=""
if command -v python3.12 &>/dev/null; then
  PYTHON="python3.12"
elif python3 -c "import sys; assert sys.version_info[:2] == (3, 12)" &>/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "Error: Python 3.12 is required (matching CI)." >&2
  echo "Install it (e.g. 'mise use python@3.12') and ensure 'python3.12' is on PATH." >&2
  exit 1
fi

# ── Venv + pip-tools ───────────────────────────────────────────

VENV_DIR="$(mktemp -d)"
trap 'rm -rf "$VENV_DIR"' EXIT
"$PYTHON" -m venv "$VENV_DIR"
# Bootstrap pip-tools from its own hashed lock for supply-chain integrity.
"$VENV_DIR/bin/pip" install --quiet --require-hashes -r "$REPO_ROOT/tests/build-requirements.lock"

# ── Compile ────────────────────────────────────────────────────

compile() {
  local src="$1" out="$2"
  local tmp="" existing_stripped="" new_stripped=""
  if [[ "$CHECK" -eq 1 ]]; then
    # Set trap before mktemp so partial failures don't leak files.
    trap 'rm -f ${tmp:+"$tmp"} ${existing_stripped:+"$existing_stripped"} ${new_stripped:+"$new_stripped"}' RETURN
    tmp=$(mktemp)
    existing_stripped=$(mktemp)
    new_stripped=$(mktemp)
    # Run from REPO_ROOT so pip-compile records relative paths in the header.
    # Compiling into an empty mktemp file (not --output-file "$out") means there's no
    # existing pin to seed from, so this resolution is fresh by construction and needs
    # no --upgrade (unlike the generate branch below). See #481.
    (cd "$REPO_ROOT" && "$VENV_DIR/bin/pip-compile" \
      --generate-hashes \
      --allow-unsafe \
      --resolver=backtracking \
      --quiet \
      --no-header \
      --output-file "$tmp" \
      "$src")
    if [[ ! -f "$REPO_ROOT/$out" ]]; then
      echo "::error::$out does not exist. Run scripts/lock-pip-requirements.sh to generate it." >&2
      return 1
    fi
    # Strip header from the existing lockfile for comparison
    grep -v '^#' "$REPO_ROOT/$out" | grep -v '^$' > "$existing_stripped" || true
    grep -v '^#' "$tmp" | grep -v '^$' > "$new_stripped" || true
    if ! diff -q --ignore-blank-lines "$existing_stripped" "$new_stripped" >/dev/null 2>&1; then
      echo "::error::$out is out of date. Run scripts/lock-pip-requirements.sh to regenerate." >&2
      return 1
    fi
    trap - RETURN
    echo "$out is up to date."
  else
    # Run from REPO_ROOT so pip-compile records relative paths in the header.
    # --upgrade forces a fresh re-resolution: without it, pip-compile treats the
    # existing --output-file as a pin seed and keeps stale-but-still-valid pins
    # (the --check branch avoids this by compiling into an empty mktemp). See #481.
    # This re-resolves ALL three lockfiles' transitive pins on every run (not just
    # ones affected by a source-file change) — see --help for the user-facing note.
    (cd "$REPO_ROOT" && "$VENV_DIR/bin/pip-compile" \
      --upgrade \
      --generate-hashes \
      --allow-unsafe \
      --resolver=backtracking \
      --output-file "$out" \
      "$src")
    echo "Generated $out"
  fi
}

compile tests/requirements.txt tests/requirements.lock
compile tests/release-requirements.txt tests/release-requirements.lock
compile tests/build-requirements.txt tests/build-requirements.lock

echo "Done."
