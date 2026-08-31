#!/usr/bin/env bash
# ==============================================================================
# FLOYDIA SUITE (F-SUITE) — LAUNCHER SCRIPT
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "venv/bin/python3" ]; then
    exec ./venv/bin/python3 floydia_suite_app.py "$@"
else
    exec python3 floydia_suite_app.py "$@"
fi
