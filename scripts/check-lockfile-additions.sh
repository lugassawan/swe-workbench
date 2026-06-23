#!/usr/bin/env bash
set -euo pipefail

# ── Usage ──────────────────────────────────────────────────────────────────

if [[ $# -eq 0 ]]; then
  echo "Error: no lockfile paths given" >&2
  echo "Usage: $0 <lockfile> [<lockfile> ...]" >&2
  exit 1
fi

# ── Top-level extractor ────────────────────────────────────────────────────
# Reads pip-compile lock content on stdin.
# A package is top-level iff any line in its # via block matches -r *.txt.
# Outputs sorted package names, one per line.

extract_top_level() {
  awk '
    /^[A-Za-z0-9._-]+==/ {
      name = $1
      sub(/==.*/, "", name)
      invia = 0
      next
    }
    /^[[:space:]]*#[[:space:]]*via/ {
      invia = 1
      if ($0 ~ /-r[[:space:]].*\.txt/) top[name] = 1
      next
    }
    invia && /^[[:space:]]*#/ {
      if ($0 ~ /-r[[:space:]].*\.txt/) top[name] = 1
      next
    }
    { invia = 0 }
    END { for (p in top) if (p != "") print p }
  ' | sort -u
}

# ── Per-lockfile check ─────────────────────────────────────────────────────

failed=0

for lock in "$@"; do
  # Base set: HEAD content (pre-regen, pre-commit).
  # When the lockfile is new (absent from HEAD), every package is treated as an
  # addition — this is intentional; a new lockfile always requires human review.
  if git cat-file -e "HEAD:${lock}" 2>/dev/null; then
    base=$(git show "HEAD:${lock}" | extract_top_level)
  else
    base=""
  fi

  # New set: working-tree content (post-regen).
  if [[ ! -f "${lock}" ]]; then
    echo "::error::${lock}: file not found in working tree" >&2
    failed=1
    continue
  fi
  new=$(extract_top_level < "${lock}")

  # Additions: packages in new that are absent from base.
  # Filter empty lines so an empty base doesn't false-positive.
  added=$(comm -13 \
    <(printf '%s\n' "${base}" | grep -v '^$') \
    <(printf '%s\n' "${new}"  | grep -v '^$'))

  if [[ -n "${added}" ]]; then
    echo "::error::${lock}: new top-level package(s) added — review before merging:" >&2
    while IFS= read -r pkg; do
      echo "  ${pkg}" >&2
    done <<< "${added}"
    failed=1
  fi
done

if [[ "${failed}" -eq 1 ]]; then
  exit 1
fi
