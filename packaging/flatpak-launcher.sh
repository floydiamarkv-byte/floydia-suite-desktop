#!/usr/bin/env bash
# Launcher para Flatpak — cambia al directorio de datos y lanza la suite.
set -e
cd /app/share/floydia-suite
exec python3 floydia_suite_app.py "$@"