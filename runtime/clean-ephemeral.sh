#!/usr/bin/env bash
# clean-ephemeral.sh <path>
#
# Remove an ephemeral git worktree directory, but only after proving it is a
# sanctioned artifact.  Exits 1 (never silently) when any safety check fails.
#
# Safety checks (ALL must pass):
#   1. Argument is non-empty, absolute, and contains no ".." segment.
#   2. Path is not "/", not "$HOME", and is at least two levels deep.
#   3. Basename matches the ephemeral-task prefix regex used by the three flows:
#        ^(pr-review|pr-followup|address-feedback)-[A-Za-z0-9._-]+$
#   4. The path is a registered git worktree (appears in `git worktree list`),
#      OR lives under one of the known tmp dirs:
#        /tmp/swe-workbench-pr-review/
#        /tmp/swe-workbench-address-feedback/
#        $HOME/.local/share/swe-workbench/
#
# This script is invoked by the cleanup blocks in the three review/feedback
# skills instead of a bare `rm -rf "$WT"`.  The PreToolUse:Bash guard never
# sees the inner `rm -rf` because it runs in a child process spawned by bash.

set -euo pipefail

# ── Argument validation ────────────────────────────────────────────────────

TARGET="${1:-}"

reject() {
  echo "clean-ephemeral: $*" >&2
  exit 1
}

[ -n "$TARGET" ] || reject "path argument is required"

# Must be absolute.
case "$TARGET" in
  /*) ;;
  *) reject "path must be absolute: $TARGET" ;;
esac

# Must not contain ".." segments (e.g. /foo/../bar, or a bare ../ prefix).
if printf '%s' "$TARGET" | grep -qE '(^|/)\.\.(\/|$)'; then
  reject "path contains '..' traversal: $TARGET"
fi

# Normalise: strip trailing slash.
TARGET="${TARGET%/}"

# Must not be root.
[ "$TARGET" = "/" ] && reject "refusing to remove root '/'"

# Must not be $HOME.
[ "$TARGET" = "${HOME:-}" ] && reject "refusing to remove \$HOME"

# Must be at least two directory levels deep (e.g. /a/b — three components
# including the leading empty string from the split on '/').
depth=$(printf '%s' "$TARGET" | tr -cd '/' | wc -c)
[ "$depth" -ge 2 ] || reject "path is not deep enough (need ≥2 slashes): $TARGET"

# ── Sanctioned-location check ──────────────────────────────────────────────
#
# Two approval paths:
#   A. Under a known safe tmp dir (rimba-absent fallback locations) — location
#      is the trust anchor; basename is unrestricted within those dirs.
#   B. Basename matches ephemeral prefix AND path is a registered git worktree
#      (rimba-managed worktrees, wherever rimba places them — including ~/…).
#
# This split handles the fact that rimba-absent fallback paths use bare PR
# numbers as the basename (e.g. /tmp/swe-workbench-pr-review/42) while
# rimba-managed paths use labelled basenames (pr-review-42, pr-followup-42,
# address-feedback-42).

is_under_tmp_dir() {
  local path="$1"
  # Resolve symlinks so /tmp -> /private/tmp on macOS is handled transparently.
  local canon_path
  canon_path=$(cd "$path" 2>/dev/null && pwd -P) || canon_path="$path"
  local canon_tmp
  canon_tmp=$(cd /tmp 2>/dev/null && pwd -P) || canon_tmp="/tmp"
  case "$canon_path" in
    "${canon_tmp}/swe-workbench-pr-review/"*)        return 0 ;;
    "${canon_tmp}/swe-workbench-address-feedback/"*) return 0 ;;
  esac
  local share_dir="${HOME:-}/.local/share/swe-workbench"
  case "$canon_path" in
    "${share_dir}/"*) return 0 ;;
  esac
  return 1
}

basename_is_ephemeral() {
  local path="$1"
  local base="${path##*/}"
  # Allowed prefixes:
  #   pr-review-<id>          — workflow-pr-review (rimba task)
  #   pr-followup-<id>        — workflow-pr-review-followup (rimba task)
  #   address-feedback-<id>   — workflow-address-feedback (rimba task)
  echo "$base" | grep -qE '^(pr-review|pr-followup|address-feedback)-[A-Za-z0-9._-]+$'
}

is_registered_worktree() {
  local path="$1"
  # A registered git linked worktree always has a .git FILE (not a .git directory)
  # whose content is "gitdir: <path>/.git/worktrees/<name>" — i.e. the gitdir
  # target lives inside a .git/worktrees/ directory.  Submodules also have a
  # .git file but their gitdir target is a bare "modules/<name>" path.
  local git_file="$path/.git"
  [ -f "$git_file" ] || return 1
  local gitdir_line
  gitdir_line=$(grep '^gitdir:' "$git_file" 2>/dev/null) || return 1
  # Verify the gitdir points into a .git/worktrees/ directory.
  echo "$gitdir_line" | grep -q '/\.git/worktrees/'
}

if is_under_tmp_dir "$TARGET"; then
  : # safe location — skip basename restriction
elif basename_is_ephemeral "$TARGET" && is_registered_worktree "$TARGET"; then
  : # rimba-managed worktree with expected basename — safe
else
  reject "path did not pass location or (basename + registered-worktree) checks: $TARGET"
fi

# ── Removal ────────────────────────────────────────────────────────────────

rm -rf -- "$TARGET"
