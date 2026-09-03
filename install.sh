#!/usr/bin/env bash
# ==============================================================================
# FLOYDIA SUITE (F-SUITE) — AUTOMATED INSTALLER & ENVIRONMENT SETUP
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "⚡ Instalando FloydIA Suite (F-Suite)..."

# 1. Verificar Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 no está instalado. Por favor instálalo en tu sistema."
    echo "   Debian/Ubuntu:  sudo apt install python3"
    echo "   Arch/Fedora:    sudo pacman -S python / sudo dnf install python3"
    exit 1
fi

# 1b. Verificar python3-venv / ensurepip (BUG-06): falla claro en distros sin paquete separado
if ! python3 -m venv --help > /dev/null 2>&1; then
    echo "❌ Error: el módulo 'venv' no está disponible en este Python."
    echo "   Debian/Ubuntu:  sudo apt install python3-venv python3-pip"
    echo "   Fedora:         sudo dnf install python3-libs python3-pip"
    exit 1
fi
if ! python3 -c "import ensurepip" > /dev/null 2>&1; then
    echo "❌ Error: 'ensurepip' no está disponible. Instala el paquete python3-venv de tu distro."
    echo "   Debian/Ubuntu:  sudo apt install python3-venv"
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
        chmod 600 .env
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
