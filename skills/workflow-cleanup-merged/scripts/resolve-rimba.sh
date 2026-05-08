#!/usr/bin/env bash
# Resolves the rimba binary path, or prints nothing if absent.
# Stdout contract: rimba binary path on stdout, or empty string if not found.
# Exit non-zero only on a hard error (not on "rimba not installed").
set -euo pipefail

RIMBA=$(command -v rimba 2>/dev/null \
  || { [ -x "$HOME/.local/bin/rimba" ] && echo "$HOME/.local/bin/rimba"; } \
  || { [ -x "$HOME/go/bin/rimba" ]     && echo "$HOME/go/bin/rimba"; } \
  || true)

printf '%s\n' "${RIMBA:-}"
