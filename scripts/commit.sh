#!/usr/bin/env bash
# Commit staged changes via commitizen's Conventional Commits wizard
# (type + required scope, see CONTRIBUTING.md "Commit messages").
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v cz >/dev/null 2>&1; then
    echo "error: commitizen (cz) is not installed — 'brew install commitizen' (see CONTRIBUTING.md)" >&2
    exit 1
fi

cz commit "$@"
