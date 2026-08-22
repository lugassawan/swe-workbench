#!/usr/bin/env bash
set -euo pipefail

# Keeps every manifest declared in .version-bump.json in sync on a single version string.
# Adapted from obra/superpowers' bump-version.sh for this repo's own declared-file list
# (.claude-plugin/plugin.json, .claude-plugin/marketplace.json, package.json).
#
# Usage:
#   scripts/bump-version.sh <X.Y.Z>   # write <X.Y.Z> into every declared file's field
#   scripts/bump-version.sh --check   # fail if declared files disagree on version
#   scripts/bump-version.sh --audit   # fail if the current version string appears in a
#                                      # file that isn't declared (and isn't excluded)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/.version-bump.json"

if ! command -v jq &>/dev/null; then
  echo "Error: jq is required." >&2
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "Error: ${CONFIG} not found." >&2
  exit 1
fi

# Emits one "path<TAB>field" line per declared file. A plain jq call (no pipe into another
# command) so nothing here can trip `set -o pipefail` via an early-closing consumer.
_declared_files() {
  jq -r '.files[] | [.path, .field] | @tsv' "$CONFIG"
}

MODE="${1:-}"

case "$MODE" in
  --check)
    FAIL=0
    EXPECTED=""
    while IFS=$'\t' read -r path field; do
      VER=$(jq -r "$field" "${ROOT}/${path}")
      if [[ -z "$EXPECTED" ]]; then
        EXPECTED="$VER"
      elif [[ "$VER" != "$EXPECTED" ]]; then
        echo "Error: ${path} (${field}) = ${VER}, expected ${EXPECTED}" >&2
        FAIL=1
      fi
      echo "${path} (${field}): ${VER}"
    done < <(_declared_files)
    [[ "$FAIL" -eq 0 ]] || exit 1
    echo "All declared files agree on version ${EXPECTED}."
    ;;

  --audit)
    # "Current" version is read from the first declared file — direct jq calls, not a
    # pipe-into-head, so a truncated consumer can never SIGPIPE the producer under pipefail.
    FIRST_PATH=$(jq -r '.files[0].path' "$CONFIG")
    FIRST_FIELD=$(jq -r '.files[0].field' "$CONFIG")
    CURRENT=$(jq -r "$FIRST_FIELD" "${ROOT}/${FIRST_PATH}")
    echo "Auditing repo for undeclared occurrences of version ${CURRENT}..."

    DECLARED_PATHS=()
    while IFS=$'\t' read -r path _field; do
      DECLARED_PATHS+=("$path")
    done < <(_declared_files)

    # ".git" is always excluded, regardless of what .version-bump.json declares.
    EXCLUDES=(".git")
    while IFS= read -r ex; do
      [[ -n "$ex" ]] && EXCLUDES+=("$ex")
    done < <(jq -r '.audit.exclude[]? // empty' "$CONFIG")

    # Exclusion is done in plain bash below, not via grep's --exclude-dir/--exclude flags:
    # macOS's default /usr/bin/grep is an old BSD grep whose directory-exclude support is
    # unreliable (verified: it still descended into node_modules with --exclude-dir set), and a
    # release engineer's interactive shell may alias `grep` to yet another implementation with
    # its own quirks. A plain recursive grep plus a portable prefix filter works the same
    # everywhere.
    HITS=()
    while IFS= read -r hit; do
      [[ -n "$hit" ]] && HITS+=("$hit")
    done < <(cd "$ROOT" && grep -rl --fixed-strings -- "$CURRENT" . 2>/dev/null | sed 's#^\./##')

    _under_prefix() {
      # $1 = candidate path, $2 = prefix (an exact file, or a directory whose contents
      # should also match). A directory prefix must be followed by "/" to avoid a false
      # match like "docs-old" against exclude entry "docs". Strip a trailing "/" from $2
      # first: an idiomatic .gitignore-style exclude entry ("node_modules/") would
      # otherwise produce a double-slash glob ("node_modules//*") that never matches a
      # real single-slash path.
      local prefix="${2%/}"
      [[ "$1" == "$prefix" || "$1" == "$prefix"/* ]]
    }

    # Any-depth matching is EXCLUDES-only: a bare DECLARED_PATHS entry like "package.json" must
    # stay anchored (via the unmodified _under_prefix), or vendor/package.json would wrongly
    # count as declared and a real undeclared hit would go unreported.
    _matches_exclude() {
      local candidate="$1" entry="$2"
      if _under_prefix "$candidate" "$entry"; then
        return 0
      fi
      local name="${entry%/}"
      if [[ "$name" == */* ]]; then
        return 1
      fi
      [[ "$candidate" == *"/${name}" || "$candidate" == *"/${name}/"* ]]
    }

    UNDECLARED=()
    for hit in "${HITS[@]}"; do
      skip=0
      for d in "${DECLARED_PATHS[@]}"; do
        if _under_prefix "$hit" "$d"; then
          skip=1
          break
        fi
      done
      if [[ "$skip" -eq 0 ]]; then
        for ex in "${EXCLUDES[@]}"; do
          if _matches_exclude "$hit" "$ex"; then
            skip=1
            break
          fi
        done
      fi
      [[ "$skip" -eq 1 ]] || UNDECLARED+=("$hit")
    done

    if [[ "${#UNDECLARED[@]}" -gt 0 ]]; then
      echo "Error: version string '${CURRENT}' found in undeclared file(s):" >&2
      printf '  %s\n' "${UNDECLARED[@]}" >&2
      echo "Add these to .version-bump.json's files list, or audit.exclude if intentional." >&2
      exit 1
    fi
    echo "No undeclared occurrences of ${CURRENT} found."
    ;;

  "")
    echo "Usage: $0 <X.Y.Z> | --check | --audit" >&2
    exit 1
    ;;

  *)
    NEXT="$MODE"
    if [[ ! "$NEXT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "Error: version must be X.Y.Z, got '${NEXT}'" >&2
      exit 1
    fi
    while IFS=$'\t' read -r path field; do
      TARGET="${ROOT}/${path}"
      TMP=$(mktemp)
      jq --arg v "$NEXT" "${field} = \$v" "$TARGET" > "$TMP" && mv "$TMP" "$TARGET"
      echo "Updated ${path} (${field}) -> ${NEXT}"
    done < <(_declared_files)
    ;;
esac
