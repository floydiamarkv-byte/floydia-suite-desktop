#!/usr/bin/env bash
# ==============================================================================
# FloydIA Suite 2.0 — Generador de AppImage (portable, sin instalación)
# Requiere: python3, python-appimage (pip install python-appimage) o linuxdeploy
# Uso:      ./make_appimage.sh   →  dist/FloydIA-Suite-x86_64.AppImage
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo "⚡ Construyendo AppImage de FloydIA Suite..."

# Preflight: dependencias de build
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 requerido"; exit 1
fi

# Paso 1: empaquetar el árbol en un AppDir portable
APPDIR="build/AppDir"
rm -rf "$APPDIR" build/dist
mkdir -p "$APPDIR/usr/src/floydia-suite" "$APPDIR/usr/bin"

cp -r floydia_suite_app.py theme.py requirements.txt README.md "$APPDIR/usr/src/floydia-suite/"
cp -r modules "$APPDIR/usr/src/floydia-suite/"
cp -r assets "$APPDIR/usr/src/floydia-suite/" 2>/dev/null || true
cp packaging/floydia-suite.desktop "$APPDIR/floydia-suite.desktop"
cp assets/icon.png "$APPDIR/FloydIA-Suite.png" 2>/dev/null || true

# Launcher que cambia al dir de datos (rutas YAML/JSON relativas al árbol)
cat > "$APPDIR/usr/bin/floydia-suite" <<EOF
#!/usr/bin/env bash
set -e
cd "\$(dirname "\$(readlink -f "\$0")")/../src/floydia-suite"
exec ./run.sh "\$@"
EOF
chmod +x "$APPDIR/usr/bin/floydia-suite"

# Paso 2: convertir a AppImage con python-appimage (Python 3.10+ runtime incluido)
MISSING=
[ -d venv ] && VENV_BIN=venv/bin || VENV_BIN=
if [ -n "$VENV_BIN" ] && [ -x "$VENV_BIN/python-appimage" ]; then
    PYAPP="$VENV_BIN/python-appimage"
else
    PYAPP="$(command -v python-appimage || true)"
fi
if [ -z "${PYAPP:-}" ]; then
    echo "⚠️ python-appimage no encontrado. Construyendo AppDir (listo para linuxdeploy):"
    echo "   python3 -m pip install python-appimage --user"
    echo "   linuxdeploy-x86_64.AppImage --appdir build/AppDir --output appimage"
    mkdir -p build/dist
    echo "AppDir listo: build/AppDir — convierte con linuxdeploy o python-appimage."
    exit 0
fi

"$PYAPP" build/AppDir --python-version 3.10 -p "PyQt6,psutil,PyYAML" \
    --output-dir build/dist 2>&1 | tail -5
echo "✅ AppImage generado: build/dist/"
ls -lh build/dist/