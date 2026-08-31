#!/usr/bin/env bash
# ==============================================================================
# FLOYDIA SUITE (F-SUITE) — AUTOMATED INSTALLER & ENVIRONMENT SETUP
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "⚡ Instalando FloydIA Suite (F-Suite)..."

# 1. Verificar Python 3 y PyQt6 dependencies
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 no está instalado. Por favor instálalo en tu sistema."
    exit 1
fi

# 2. Crear entorno virtual si no existe
if [ ! -d "venv" ]; then
    echo "📦 Creando entorno virtual (venv)..."
    python3 -m venv venv
fi

# 3. Activar e instalar dependencias
echo "📥 Instalando dependencias de requirements.txt..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Crear archivo .env si no existe
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "📝 Creando plantilla inicial .env desde .env.example..."
        cp .env.example .env
    fi
fi

# 5. Crear directorio de cache y reportes
mkdir -p cache reports

# 6. Hacer ejecutable el script de lanzamiento
chmod +x run.sh || true

echo ""
echo "======================================================================"
echo "✅ FloydIA Suite (F-Suite) instalada exitosamente."
echo "💡 Para iniciar la suite ejecuta:"
echo "   ./run.sh"
echo "======================================================================"
