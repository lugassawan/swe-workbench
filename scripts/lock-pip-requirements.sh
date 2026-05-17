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
      echo "  Regenerates tests/requirements.lock and tests/release-requirements.lock"
      echo "  from their source files using pip-compile --generate-hashes, targeting"
      echo "  Python 3.12 (matching CI)."
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

VENV_DIR="/tmp/pip-lock-venv"
"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet pip-tools

# ── Compile ────────────────────────────────────────────────────

compile() {
  local src="$1" out="$2"
  if [[ "$CHECK" -eq 1 ]]; then
    local tmp
    tmp=$(mktemp)
    "$VENV_DIR/bin/pip-compile" \
      --generate-hashes \
      --resolver=backtracking \
      --quiet \
      --no-header \
      --output-file "$tmp" \
      "$REPO_ROOT/$src"
    # Strip header from the existing lockfile for comparison
    local existing_stripped
    existing_stripped=$(mktemp)
    grep -v '^#' "$REPO_ROOT/$out" | grep -v '^$' > "$existing_stripped" || true
    local new_stripped
    new_stripped=$(mktemp)
    grep -v '^#' "$tmp" | grep -v '^$' > "$new_stripped" || true
    if ! diff -q --ignore-blank-lines "$existing_stripped" "$new_stripped" >/dev/null 2>&1; then
      echo "::error::$out is out of date. Run scripts/lock-pip-requirements.sh to regenerate." >&2
      rm -f "$tmp" "$existing_stripped" "$new_stripped"
      return 1
    fi
    rm -f "$tmp" "$existing_stripped" "$new_stripped"
    echo "$out is up to date."
  else
    "$VENV_DIR/bin/pip-compile" \
      --generate-hashes \
      --resolver=backtracking \
      --output-file "$REPO_ROOT/$out" \
      "$REPO_ROOT/$src"
    echo "Generated $out"
  fi
}

compile tests/requirements.txt tests/requirements.lock
compile tests/release-requirements.txt tests/release-requirements.lock

echo "Done."
