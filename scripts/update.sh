#!/usr/bin/env bash
# Reinstall tito after local changes to tito.py: re-copies the binary to
# ~/.local/bin/tito and re-registers the Claude Code hook (see cmd_install).
set -euo pipefail
cd "$(dirname "$0")/.."

python3 tito.py install
