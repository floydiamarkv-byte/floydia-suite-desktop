# ⚡ FloydIA Suite (F-Suite) — Desktop Command Center & AI Orchestrator

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)](https://riverbankcomputing.com/software/pyqt/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Linux Platform](https://img.shields.io/badge/platform-Linux-orange.svg)]()
[![Code Style: Clean](https://img.shields.io/badge/architecture-P0%20Hardened-brightgreen.svg)]()

> **FloydIA Suite (F-Suite)** es un Centro de Comando Unificado para Linux Desktop (PyQt6), diseñado para monitorear la salud de flotas de modelos LLM en tiempo real, optimizar la latencia del sistema (SRE Governor), gestionar servidores MCP (Model Context Protocol) y propagar configuraciones multi-cuenta en 1-clic hacia agentes de desarrollo (**OpenCode**, **Hermes**, **Zed** y Homelab).

---

## 🌟 Características Principales

```
 ┌──────────────────────────────────────────────────────────────────────────────────┐
 │                         ⚡ FLOYDIA SUITE 2.0 (F-SUITE)                           │
 ├────────────────────┬────────────────────┬────────────────────┬───────────────────┤
 │ 🛰️ AI Radar        │ 🎛️ MCP & Skills    │ 🔑 Multi-Acc APIs  │ 🧹 SRE Cleaner    │
 │   • Live Telemetry │   • 6-Agent Sync   │   • 1-Click Sync   │   • BleachBit Eng │
 │   • Context Filter │   • Server Cockpit │   • DeepSeek V3/R1 │   • Bitwarden Safe│
 │   • TPS & Latency  │   • Token Budget   │   • Multi-Account  │   • Multi-Profile │
 ├────────────────────┼────────────────────┼────────────────────┼───────────────────┤
 │ ⚡ SRE Governor    │ 📡 Network Diag    │ 🔄 Reboot Hub      │ 💾 Atomic State   │
 │   • RAM Optimizer  │   • Live Probes    │   • Proxmox & APs  │   • fcntl.flock   │
 │   • Action Journal │   • Homelab Health │   • Graceful Flow  │   • Fast Restore  │
 └────────────────────┴────────────────────┴────────────────────┴───────────────────┘
```

### 1. 🛰️ AI Radar & Observatorio de Modelos
* **Sondeo en Vivo Concurrente**: Medición en tiempo real de latencia (ms), TTFT (Time to First Token), TPS (Tokens per Second) y detección de errores de cuota (HTTP 402/429).
* **Filtro Avanzado de Ventana de Contexto**: Filtra al instante modelos escaneados por tamaño de contexto (`≥ 32k`, `≥ 128k`, `≥ 200k`, `≥ 1M tokens`).
* **Descargador de Catálogos Globales**: Importación y filtrado inteligente de más de 400 modelos desde OpenRouter, NVIDIA NIM, Google AI Studio, DeepSeek y Mistral.
* **Exportador Multi-Cuenta DeepSeek**: Diálogo de inspección y exportación directa de flotas DeepSeek V3 / R1 en formato JSON/YAML listo para arneses.
* **Exportador de Reportes Ejecutivos**: Generación con 1-clic de informes ejecutivos en formato **Markdown (.md)** y **HTML interactivo**.
* **Módulo Asesor IA Integrado**: Consulta a modelos locales o remotos para analizar la telemetría y recomendar el mejor modelo costo/eficiencia para tu tarea.

### 2. 🎛️ MCP Cockpit & Skills Studio
* **Gestor de Servidores MCP**: Control granular de activación y desactivación de servidores Model Context Protocol (`~/.gemini/config/mcp_config.json`).
* **Propagación Atómica 1-Clic REAL a Todos los Agentes** *(desde 2026-10-12)*: al pulsar **"Guardar y Aplicar"**, la suite **escribe directamente** (no solo exporta fragmentos) los MCPs activos hacia:
  * **Antigravity IDE / agy CLI**: `~/.gemini/config/mcp_config.json` (SSOT del cockpit)
  * **OpenCode**: `~/.config/opencode/opencode.jsonc` (fusión no destructiva: preserva entradas manuales)
  * **Hermes Agent**: `~/.hermes/config.yaml` (bloque `mcp_servers`)
  * **DeepSeek Harness (DSH)**: regenera `~/.dsh/profiles/web/cordis.patch.yml` vía el sincronizador canónico
* **Seguridad auditable**: toda escritura sobre configs del harness pasa por la vía autorizada (`write_harness_owned` / `_harness_write_grant`, con `reason` trazable por `grep`), genera backup `*.bak-suite` y copia de auditoría en `cache/`. El test `test_no_ssot_writes.py` vigila que ninguna escritura ocurra fuera de esa vía.
* **Preset 🎨 Diseño Web**: activación 1-clic del stack de skills de diseño (accessibility, best-practices, core-web-vitals, performance, seo, web-quality-audit).
* **Presupuesto de Tokens de Skills**: Monitoreo visual de skills de agentes activos para asegurar un consumo óptimo (<700 tokens).

### 3. 🔑 API Manager & Propagación Multi-Cuenta
* **Taxonomía Multi-Cuenta [C1..C8]**: Gestión centralizada de cuentas principales, secundarias y de respaldo para Google AI Studio, OpenRouter, DeepSeek, NVIDIA NIM y Mistral.
* **Propagación 1-Clic a Agentes**: Generación determinista y atómica de configuraciones con whitelists y control de modelos habilitados para OpenCode, Hermes, Zed y DSH.
* **Soporte Completo DeepSeek**: Mapeo directo de `deepseek-chat` (V3) y `deepseek-reasoner` (R1) con soporte para streams de `reasoning_content` y fallbacks automáticos.

### 4. 🧹 SRE BleachBit Cleaner — Limpieza Segura Multi-Perfil
* **Motor de Limpieza BleachBit**: Limpieza modular con modos Previsualización (Dry-Run) y Ejecución Real.
* **Allowlist Inmutable de Seguridad**: Blindaje absoluto contra borrado accidental de bóvedas de **Bitwarden** (`nngceckbapebfimnlniiiahkandclblb`), extensiones de navegador y credenciales maestras.
* **Soporte Multi-Navegador**: Limpieza profunda de cachés, IndexedDB, GPUCache y Service Workers para Chromium, Chrome, Brave, Edge y Vivaldi preservando sesiones activas.
* **Optimización de Sistema**: Limpieza segura de cachés de paquetes (`pacman`/`apt`), logs huérfanos de systemd y temporales de usuario.

### 5. ⚡ SRE Governor & Optimización de Memoria
* **Monitor de Recursos en Vivo**: Telemetría continua de CPU, memoria RAM, SWAP y carga del sistema.
* **Acciones de Optimización**: Liberación segura de PageCache/dentries, purga de procesos zombies y ajuste de perfiles de rendimiento.
* **Action Journal**: Registro de auditoría JSONL estructurado con marcas de tiempo y métricas de duración.

### 6. 🔄 Control de Infraestructura & Reboot Hub
* **Orquestación de Nodos Homelab**: Monitor de salud y reinicio ordenado de Proxmox VE, Puntos de Acceso MikroTik, Routers y Hosts locales.
* **Reinicio Seguro con Cuenta Regresiva**: Ventanas de confirmación y temporizador cancelable de 10 segundos para el host principal.

### 7. 📡 Diagnóstico de Red y Conectividad
* **Probes Concurrentes en Paralelo (`ThreadPoolExecutor`)**: Monitoreo multihilo ultrarrápido de latencias hacia Gateway local, nodos Proxmox/Homelab y DNS WAN (Cloudflare, Google).

---

## 📋 Requisitos del Sistema

* **Sistema Operativo**: Linux (Arch Linux, EndeavourOS, Debian, Ubuntu, Fedora, Pop!_OS, etc.).
* **Python**: `3.10` o superior.
* **Bibliotecas**: `PyQt6`, `PyYAML`, `psutil`, `urllib3`.

---

## 🚀 Instalación Rápida

### Paso 1: Clonar el repositorio
```bash
git clone https://github.com/floydiamarkv-byte/floydia-suite-desktop.git
cd floydia-suite-desktop
```

### Paso 2: Ejecutar el instalador automatizado
El script creará un entorno virtual aislado (`venv`) e instalará todas las dependencias:
```bash
chmod +x install.sh run.sh
./install.sh
```

### Paso 3: Configurar tus API Keys
Copia la plantilla de variables de entorno y añade tus claves de API:
```bash
cp .env.example .env
nano .env   # o tu editor favorito (code, zed, vim)
```

*(Opcional: Si no configuras `.env`, puedes añadir y gestionar tus claves directamente desde la interfaz gráfica en la pestaña "Gestor de APIs").*

### Paso 4: Iniciar FloydIA Suite
```bash
./run.sh
```

---

## ⚙️ Variables de Entorno Soportadas (`.env`)

| Variable | Proveedor | Descripción |
|---|---|---|
| `GOOGLE_API_KEY` / `C1_GOOGLE_AISTUDIO` | Google AI Studio | Acceso a Gemini 2.5 Pro, 3.7 Flash, Gemma |
| `OPENROUTER_API_KEY` / `C7_OPENROUTER` | OpenRouter | Acceso al hub global (+400 modelos) |
| `DEEPSEEK_API_KEY` / `C1_DEEPSEEK` | DeepSeek Direct | Acceso a DeepSeek V3 y Reasoner R1 |
| `NVIDIA_API_KEY` / `C7_NVIDIA` | NVIDIA NIM | Endpoints dedicados de inferencia acelerada |
| `MISTRAL_API_KEY` / `C1_MISTRAL` | Mistral AI | Acceso a Codestral y Mistral Large |
| `GATEWAY_IP` | Red Local | IP para probe de Gateway (Default: `192.168.1.1`) |
| `HOMELAB_IP` | Homelab | IP para probe de Servidor Local (Default: `127.0.0.1`) |

---

## 🛡️ Seguridad y Buenas Prácticas (P0 Hardened)

1. **Anti-Fuga de Credenciales (`sanitize_for_persistence`)**:
   * Las claves de API y tokens sensibles **nunca** se guardan en texto plano en los archivos de telemetría, logs o reportes exportados.
2. **Escrituras Atómicas y Thread-Safety (`fcntl.flock`)**:
   * Toda modificación de archivos de configuración utiliza bloqueo atómico para evitar corrupción en entornos multi-proceso o multi-hilo.
3. **Shutdown Determinista y Concurrencia Cooperativa**:
   * Los hilos de sondeo implementan `CancellableThread` con detención cooperativa en menos de 2 segundos, garantizando un cierre limpio sin fugas de memoria.

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Si deseas añadir nuevos proveedores de modelos, mejorar la integración con otros editores de código o aportar nuevos widgets:

1. Haz un Fork del proyecto.
2. Crea una rama para tu feature (`git checkout -b feature/nueva-mejora`).
3. Realiza tus commits (`git commit -m 'feat: Añadir soporte para nuevo provider'`).
4. Haz push a la rama (`git push origin feature/nueva-mejora`).
5. Abre un **Pull Request**.

---

## 📦 Changelog

### 2026-10-12 — Propagación MCP 1-clic real + Cockpit multi-tenant
- **Propagación automática**: el *MCP Cockpit* ya no exporta fragmentos para fusión manual — escribe directamente y de forma atómica en OpenCode, Hermes y DSH, con backup `*.bak-suite` y escritura auditable (`write_harness_owned` / `_harness_write_grant`).
- **`test_no_ssot_writes.py`** actualizado: la política pasa de "nunca escribir" a "escribir solo por la vía auditable", con control positivo intacto.
- **Preset 🎨 Diseño Web** en Skills Studio (accessibility, best-practices, core-web-vitals, performance, seo, web-quality-audit).
- **Fix tenant Novamira**: `novamira-mcp` era dinámico (fallback a Wattsaver) y se renombra a `novamira-evergreen`; añadidos los tenants `novamira-wattsaver`, `novamira-floydia`, `novamira-coquita` y `novamira-kuamikiachi` como entradas independientes activables desde el Cockpit.
- **32/32 tests** en verde.

---

## 📄 Licencia

Distribuido bajo la Licencia **MIT**. Consulta el archivo [`LICENSE`](LICENSE) para más detalles.

---

<p align="center">
  <b>FloydIA Suite (F-Suite)</b> — <i>Diseñado para desarrolladores de IA, ingenieros SRE y entusiastas del Homelab.</i>
</p>
