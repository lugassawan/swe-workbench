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

# ── All-packages extractor ─────────────────────────────────────────────────
# Same package set, but ignores the -r *.txt predicate — every pinned
# package (top-level or transitive) is included.

extract_all_packages() {
  awk '
    /^[A-Za-z0-9._-]+==/ {
      name = $1
      sub(/==.*/, "", name)
      if (name != "") print name
    }
  ' | sort -u
}

# ── Per-lockfile check ─────────────────────────────────────────────────────

failed=0

for lock in "$@"; do
  # Base set: HEAD content (pre-regen, pre-commit).
  # NOTE: baseline is HEAD, not main — on a `synchronize` after the bot has
  # already committed a regen to this branch, a transitive package warned on
  # in an earlier push won't re-warn. Acceptable: this signal is non-blocking.
  # When the lockfile is new (absent from HEAD), every package is treated as an
  # addition — this is intentional; a new lockfile always requires human review.
  if git cat-file -e "HEAD:${lock}" 2>/dev/null; then
    base_content=$(git show "HEAD:${lock}")
    base=$(printf '%s\n' "${base_content}" | extract_top_level)
    base_all=$(printf '%s\n' "${base_content}" | extract_all_packages)
  else
    base=""
    base_all=""
  fi

  # New set: working-tree content (post-regen).
  if [[ ! -f "${lock}" ]]; then
    echo "::error::${lock}: file not found in working tree" >&2
    failed=1
    continue
  fi
  new=$(extract_top_level < "${lock}")
  new_all=$(extract_all_packages < "${lock}")

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

  # Transitive additions: new packages (any provenance) minus new top-level
  # additions already reported above. Non-blocking — surfaced for visibility
  # only, so the Dependabot auto-commit step keeps running.
  added_all=$(comm -13 \
    <(printf '%s\n' "${base_all}" | grep -v '^$') \
    <(printf '%s\n' "${new_all}"  | grep -v '^$'))
  added_transitive=$(comm -23 \
    <(printf '%s\n' "${added_all}" | grep -v '^$') \
    <(printf '%s\n' "${added}"     | grep -v '^$'))

  if [[ -n "${added_transitive}" ]]; then
    # `paste -d` treats a multi-char delimiter as a per-gap cycling list, not a
    # joint string (e.g. `paste -sd ', '` on 3 items yields "a,b c", not
    # "a, b, c") — join on a single char, then expand to ", " afterwards.
    names=$(paste -sd ',' - <<< "${added_transitive}")
    names=${names//,/, }
    echo "::warning::${lock}: new transitive package(s) pinned — review: ${names}"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
      echo "- ⚠️ \`${lock}\`: new transitive package(s) pinned — review: ${names}" \
        >> "${GITHUB_STEP_SUMMARY}"
    fi
  fi
done

if [[ "${failed}" -ne 0 ]]; then
  exit 1
fi
