#!/usr/bin/env bash
# Read-only preflight probe for swe-workbench runtime dependencies.
# Prints a green/red table to stdout. Writes no files. Exits 0 always.
set -uo pipefail  # -e intentionally omitted: exit 0 is required even when probes fail

MISSING=0

printf "swe-workbench preflight check\n"
printf "%s\n" "─────────────────────────────────────"

# ── gh (special: also probes auth status) ────────────────────────────────────
gh_bin=$(command -v gh 2>/dev/null) || true
if [[ -n "${gh_bin}" ]]; then
  gh_ver=$("${gh_bin}" --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) || true
  auth_out=$("${gh_bin}" auth status 2>&1) || true
  if echo "${auth_out}" | grep -qi "account "; then
    auth_user=$(echo "${auth_out}" | grep -oiE 'account [^ ]+' | head -1 | sed 's/[Aa]ccount //') || true
    auth_note="(gh auth: logged in as ${auth_user})"
  else
    auth_note="(gh auth: not logged in)"
  fi
  printf "✓  %-10s %-12s %s\n" "gh" "${gh_ver:-unknown}" "${auth_note}"
else
  printf "✗  %-10s not found  — install: https://cli.github.com\n" "gh"
  MISSING=$((MISSING + 1))
fi

# ── Generic probe function ────────────────────────────────────────────────────
probe() {
  local tool="$1"
  local ver_flag="$2"
  local hint="$3"
  local bin
  bin=$(command -v "${tool}" 2>/dev/null) || true
  if [[ -n "${bin}" ]]; then
    local ver
    ver=$("${bin}" "${ver_flag}" 2>&1 | head -1) || true
    printf "✓  %-10s %s\n" "${tool}" "${ver:-unknown}"
  else
    printf "✗  %-10s not found  — install: %s\n" "${tool}" "${hint}"
    MISSING=$((MISSING + 1))
  fi
}

probe "git"    "--version"  "https://git-scm.com"
probe "jq"     "--version"  "https://jqlang.github.io/jq/download/"

# ── rimba: check PATH then well-known fallback locations ─────────────────────
rimba_bin=""
if command -v rimba &>/dev/null; then
  rimba_bin="$(command -v rimba)"
elif [[ -x "${HOME}/.local/bin/rimba" ]]; then
  rimba_bin="${HOME}/.local/bin/rimba"
elif [[ -x "${HOME}/go/bin/rimba" ]]; then
  rimba_bin="${HOME}/go/bin/rimba"
fi

if [[ -n "${rimba_bin}" ]]; then
  # Try --version; cobra CLIs may not support it, so suppress stderr and fall back.
  rimba_ver=$("${rimba_bin}" --version 2>/dev/null | head -1) || true
  [[ -z "${rimba_ver}" ]] && rimba_ver=$("${rimba_bin}" version 2>/dev/null | head -1) || true
  [[ -z "${rimba_ver}" ]] && rimba_ver="installed (version unknown)"
  printf "✓  %-10s %s\n" "rimba" "${rimba_ver}"
else
  printf "✗  %-10s not found  — install: go install github.com/lugassawan/rimba@latest\n" "rimba"
  MISSING=$((MISSING + 1))
fi

probe "claude"  "--version"  "https://docs.anthropic.com/en/docs/claude-code"

printf "%s\n" "─────────────────────────────────────"

if [[ ${MISSING} -eq 0 ]]; then
  printf "All dependencies present.\n"
else
  if [[ ${MISSING} -eq 1 ]]; then dep_word="dependency"; them_word="it"
  else dep_word="dependencies"; them_word="them"; fi
  printf "%d %s missing. Install %s and re-run /swe-workbench:doctor.\n" \
    "${MISSING}" "${dep_word}" "${them_word}"
fi

exit 0
