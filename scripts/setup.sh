#!/bin/sh
git config core.hooksPath "$(git rev-parse --show-toplevel)/.githooks"
echo "Git hooks enabled (.githooks/)"
