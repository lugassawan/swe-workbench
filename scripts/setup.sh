#!/bin/sh
set -e
ROOT="$(git rev-parse --show-toplevel)"
GIT_DIR="$(git rev-parse --git-dir)"
case "$GIT_DIR" in /*) ;; *) GIT_DIR="$ROOT/$GIT_DIR" ;; esac

# Remove any stale core.hooksPath — symlinks in the default location handle it.
git -C "$ROOT" config --unset core.hooksPath 2>/dev/null || true

mkdir -p "$GIT_DIR/hooks"
for src in "$ROOT"/.githooks/*; do
  name=$(basename "$src")
  ln -sfn "$ROOT/.githooks/$name" "$GIT_DIR/hooks/$name"
done

echo "Git hooks linked: $GIT_DIR/hooks/<name> -> $ROOT/.githooks/<name>"
