#!/usr/bin/env bash
# Run the full test suite (see CONTRIBUTING.md "Tests").
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m unittest discover -s tests -v
