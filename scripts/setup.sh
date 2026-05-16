#!/bin/sh
set -eu

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --help|-h)
      echo "Usage: $0 [--force]"
      echo
      echo "Installs symlinks in .git/hooks/ -> .githooks/."
      echo "Pre-existing hooks and a non-default repo-local core.hooksPath"
      echo "are preserved unless --force is passed."
      exit 0 ;;
    *) printf 'Error: unknown argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel)"
GIT_DIR="$(git rev-parse --git-dir)"
case "$GIT_DIR" in /*) ;; *) GIT_DIR="$ROOT/$GIT_DIR" ;; esac

# --- Preflight: collect conflicts ------------------------------------------
conflicts=""

existing_hp="$(git -C "$ROOT" config --local --get core.hooksPath 2>/dev/null || true)"
existing_hp="${existing_hp%/}"   # normalize trailing slash
if [ -n "$existing_hp" ] \
   && [ "$existing_hp" != ".githooks" ] \
   && [ "$existing_hp" != "$ROOT/.githooks" ]; then
  conflicts="${conflicts}  core.hooksPath = $existing_hp (expected unset or .githooks)
"
fi

mkdir -p "$GIT_DIR/hooks"
for src in "$ROOT"/.githooks/*; do
  [ -e "$src" ] || [ -L "$src" ] || break   # glob unexpanded — .githooks is empty or missing
  name="$(basename "$src")"
  target="$GIT_DIR/hooks/$name"
  expected="$ROOT/.githooks/$name"
  if [ -L "$target" ]; then
    [ "$(readlink "$target")" = "$expected" ] && continue   # already correct
    conflicts="${conflicts}  $target -> $(readlink "$target") (expected $expected)
"
  elif [ -e "$target" ]; then
    conflicts="${conflicts}  $target (regular file, not a symlink)
"
  fi
done

if [ -n "$conflicts" ]; then
  if [ "$FORCE" -eq 0 ]; then
    printf 'Error: setup.sh would overwrite existing hook state:\n' >&2
    printf '%s' "$conflicts" >&2
    printf 'Re-run with --force to overwrite.\n' >&2
    exit 1
  fi
  printf 'warning: --force: overwriting:\n' >&2
  printf '%s' "$conflicts" >&2
fi

# --- Apply -----------------------------------------------------------------
existing_hp_final="$(git -C "$ROOT" config --local --get core.hooksPath 2>/dev/null || true)"
existing_hp_final="${existing_hp_final%/}"
case "$existing_hp_final" in
  ""|.githooks|"$ROOT/.githooks") ;;   # unset or already correct — leave it alone
  *) git -C "$ROOT" config --local --unset core.hooksPath ;;
esac
for src in "$ROOT"/.githooks/*; do
  [ -e "$src" ] || [ -L "$src" ] || break   # glob unexpanded — .githooks is empty or missing
  name="$(basename "$src")"
  ln -sfn "$ROOT/.githooks/$name" "$GIT_DIR/hooks/$name"
done

echo "Git hooks linked: $GIT_DIR/hooks/<name> -> $ROOT/.githooks/<name>"
