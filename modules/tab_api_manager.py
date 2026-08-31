#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🔑 FLOYDIA SUITE 2.0 — Pestaña: Gestor de APIs, Endpoints & Propagación Agéntica ║
║  Administración centralizada multi-cuenta [C1..C8] de proveedores LLM           ║
║  (Google, OpenRouter, NVIDIA NIM, DeepSeek, Mistral, Groq, Z.AI, Ollama, etc.). ║
║  Propagación determinista 1-clic: OpenCode, Hermes, Zed, .env y réplica HP45.   ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.error
import fcntl
import shutil
from typing import Dict, List, Any, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QCursor, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QPlainTextEdit, QMessageBox, QComboBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QApplication, QGridLayout, QSizePolicy
)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker, is_worker_running,
    get_provider_color, get_account_badge_label
)

def find_workspace_root() -> str:
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.exists(os.path.join(curr, ".env")) or os.path.exists(os.path.join(curr, "requirements.txt")):
            return curr
        curr = os.path.dirname(curr)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKSPACE_ROOT = os.environ.get("FLOYDIA_WORKSPACE", find_workspace_root())
ENV_FILE = os.path.join(WORKSPACE_ROOT, ".env")
CACHE_DIR = os.path.join(WORKSPACE_ROOT, "cache")
APIS_CONFIG_FILE = os.path.join(CACHE_DIR, "custom_apis.json")

OPENCODE_CONFIG = os.environ.get("OPENCODE_CONFIG_PATH", os.path.expanduser("~/.config/opencode/opencode.jsonc"))
HERMES_CONFIG = os.environ.get("HERMES_CONFIG_PATH", os.path.expanduser("~/.hermes/config.yaml"))
HERMES_CACHE = os.path.expanduser("~/.hermes/provider_models_cache.json")
ZED_CONFIG = os.environ.get("ZED_CONFIG_PATH", os.path.expanduser("~/.config/zed/settings.json"))


def load_env_vars() -> Dict[str, str]:
    """Lee el archivo .env sin exponer secretos en logs."""
    env_vars = {}
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'").strip('"')
                        if " #" in v:
                            v = v.split(" #", 1)[0].strip()
                        env_vars[k] = v
        except Exception:
            pass
    return env_vars


def sanitize_api_for_disk(api: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitiza campos sensibles antes de guardar en caché JSON."""
    c = dict(api)
    # Si la clave viene de una variable de entorno, no guardamos el raw secret en disco
    if c.get("env_key") and c.get("api_key"):
        c["api_key"] = ""
    return c


def atomic_json_write(path: str, data: Any) -> None:
    """Escritura atómica thread-safe con flock y archivo temporal."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    temp_path = f"{path}.{os.getpid()}.tmp"
    lock_path = f"{path}.lock"
    try:
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


# Flota Inicial Canónica Multi-Cuenta [C1..C8]
DEFAULT_APIS: List[Dict[str, Any]] = [
    # ── Google AI Studio Multi-Cuenta (C1..C6) ──
    {
        "id": "google_c1",
        "name": "Google AI Studio Pro [C1]",
        "provider": "google",
        "account_tag": "C1",
        "env_key": "C1_GOOGLE_AISTUDIO",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "",
        "test_model": "gemini-3.7-flash",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta Principal: Gemini 3.7 Flash, 3.6, 3.5 y Gemma 4 (1M tokens)."
    },
    {
        "id": "google_c2",
        "name": "Google AI Studio [C2]",
        "provider": "google",
        "account_tag": "C2",
        "env_key": "C2_GOOGLE_AISTUDIO",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "",
        "test_model": "gemini-3.7-flash",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta Secundaria Google: Balance de carga y fallback."
    },
    {
        "id": "google_c3",
        "name": "Google AI Studio [C3]",
        "provider": "google",
        "account_tag": "C3",
        "env_key": "C3_GOOGLE_AISTUDIO",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "",
        "test_model": "gemini-3.7-flash",
        "auth_type": "Bearer",
        "enabled": False,
        "notes": "Cuenta Reserva Google C3."
    },

    # ── NVIDIA NIM Multi-Cuenta (C1, C2, C7) ──
    {
        "id": "nvidia_c7",
        "name": "NVIDIA NIM Dedicated [C7]",
        "provider": "nvidia",
        "account_tag": "C7",
        "env_key": "C7_NVIDIA",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "",
        "test_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta Primaria NIM en HP15: Modelos acelerados Hopper/Blackwell."
    },
    {
        "id": "nvidia_c1",
        "name": "NVIDIA NIM [C1]",
        "provider": "nvidia",
        "account_tag": "C1",
        "env_key": "C1_NVIDIA",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "",
        "test_model": "deepseek-ai/deepseek-v4-flash-0731",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta C1 NVIDIA NIM para DeepSeek V4 e inferencia rápida."
    },
    {
        "id": "nvidia_c2",
        "name": "NVIDIA NIM [C2]",
        "provider": "nvidia",
        "account_tag": "C2",
        "env_key": "C2_NVIDIA",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "",
        "test_model": "moonshotai/kimi-k3",
        "auth_type": "Bearer",
        "enabled": False,
        "notes": "Cuenta C2 NVIDIA NIM: Respaldo y Kimi K3."
    },

    # ── DeepSeek Direct Multi-Cuenta (C1..C7) ──
    {
        "id": "deepseek_direct",
        "name": "DeepSeek Direct API [Paid]",
        "provider": "deepseek",
        "account_tag": "Direct",
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "test_model": "deepseek-chat",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Acceso oficial directo a DeepSeek V3 y DeepSeek R1."
    },
    {
        "id": "deepseek_c1",
        "name": "DeepSeek Direct [C1]",
        "provider": "deepseek",
        "account_tag": "C1",
        "env_key": "C1_DEEPSEEK",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "test_model": "deepseek-chat",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta C1 DeepSeek: Inferencia y razonamiento R1."
    },
    {
        "id": "deepseek_c7",
        "name": "DeepSeek Direct [C7]",
        "provider": "deepseek",
        "account_tag": "C7",
        "env_key": "C7_DEEPSEEK",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "test_model": "deepseek-chat",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta C7 DeepSeek dedicada para OpenCode / Hermes."
    },

    # ── Mistral AI Multi-Cuenta (C1..C6) ──
    {
        "id": "mistral_c1",
        "name": "Mistral AI / Codestral [C1]",
        "provider": "mistral",
        "account_tag": "C1",
        "env_key": "C1_MISTRAL",
        "base_url": "https://api.mistral.ai/v1",
        "api_key": "",
        "test_model": "codestral-latest",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Especializado en código con ventana de contexto de 256k."
    },
    {
        "id": "mistral_c2",
        "name": "Mistral AI [C2]",
        "provider": "mistral",
        "account_tag": "C2",
        "env_key": "C2_MISTRAL",
        "base_url": "https://api.mistral.ai/v1",
        "api_key": "",
        "test_model": "codestral-latest",
        "auth_type": "Bearer",
        "enabled": False,
        "notes": "Cuenta de respaldo C2 Mistral."
    },

    # ── OpenRouter Multi-Cuenta (C1..C7) ──
    {
        "id": "openrouter_c7",
        "name": "OpenRouter Global Hub [C7]",
        "provider": "openrouter",
        "account_tag": "C7",
        "env_key": "C7_OPENROUTER_OPENCODE_HP15",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "test_model": "openrouter/auto",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Enrutamiento universal a +390 LLMs (Free Tier y Frontier)."
    },
    {
        "id": "openrouter_c1",
        "name": "OpenRouter Hub [C1]",
        "provider": "openrouter",
        "account_tag": "C1",
        "env_key": "C1_OPENROUTER",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "test_model": "openrouter/auto",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Cuenta C1 OpenRouter para agentes y scripts."
    },

    # ── Groq Cloud Multi-Cuenta (C1..C6) ──
    {
        "id": "groq_c1",
        "name": "Groq LPU Cloud [C1]",
        "provider": "groq",
        "account_tag": "C1",
        "env_key": "C1_GROQ",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "",
        "test_model": "llama-3.3-70b-versatile",
        "auth_type": "Bearer",
        "enabled": True,
        "notes": "Inferencia ultrarrápida LPU (500+ TPS) para LLaMA 3.3 y Mixtral."
    },

    # ── Z.AI Cloud (C1..C6) ──
    {
        "id": "zai_c1",
        "name": "Z.AI GLM Cloud [C1]",
        "provider": "zai",
        "account_tag": "C1",
        "env_key": "C1_Z_AI",
        "base_url": "https://api.z.ai/v1",
        "api_key": "",
        "test_model": "glm-4-plus",
        "auth_type": "Bearer",
        "enabled": False,
        "notes": "Inferencia nativa modelos GLM 4 / GLM 5."
    },

    # ── Homelab / Local / Direct ──
    {
        "id": "ollama_local",
        "name": "Ollama Local Homelab [Local]",
        "provider": "ollama",
        "account_tag": "Local",
        "env_key": "C1_OLLAMA",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "test_model": "llama3.2:3b",
        "auth_type": "None",
        "enabled": False,
        "notes": "Servidor local LLM en HP15 o Proxmox CT114."
    },
    {
        "id": "anthropic_direct",
        "name": "Anthropic Claude API [Direct]",
        "provider": "anthropic",
        "account_tag": "Direct",
        "env_key": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com/v1",
        "api_key": "",
        "test_model": "claude-3-5-sonnet-20241022",
        "auth_type": "x-api-key",
        "enabled": False,
        "notes": "Modelos Claude 3.5 Sonnet / Haiku."
    }
]


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: Any = None):
        super().__init__(text)
        self.sort_value = sort_value if sort_value is not None else text

    def __lt__(self, other):
        if isinstance(other, SortableTableWidgetItem):
            try:
                if isinstance(self.sort_value, (int, float)) and isinstance(other.sort_value, (int, float)):
                    return self.sort_value < other.sort_value
                if type(self.sort_value) == type(other.sort_value):
                    return self.sort_value < other.sort_value
                return float(self.sort_value) < float(other.sort_value)
            except (ValueError, TypeError):
                return str(self.sort_value) < str(other.sort_value)
        return super().__lt__(other)


class ApiPingWorker(CancellableThread):
    api_tested = pyqtSignal(str, dict)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, apis: List[Dict[str, Any]]):
        super().__init__()
        self.apis = list(apis)

    def run(self):
        self.log_signal.emit(f"⚡ Iniciando prueba de conexión (Ping) en {len(self.apis)} APIs...")
        for api in self.apis:
            if self.is_cancelled():
                break

            api_id = api.get("id", "")
            name = api.get("name", api_id)
            base_url = api.get("base_url", "").rstrip("/")
            api_key = api.get("api_key", "").strip()
            auth_type = api.get("auth_type", "Bearer")
            test_model = api.get("test_model", "default")

            if not base_url:
                res = {"status": "ERROR_URL", "latency_ms": 0, "message": "URL no configurada"}
                self.api_tested.emit(api_id, res)
                continue

            url = f"{base_url}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "FloydiaSuite/2.0-ApiManager"
            }
            if auth_type == "Bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            elif auth_type == "x-api-key" and api_key:
                headers["x-api-key"] = api_key
                headers["anthropic-version"] = "2023-06-01"

            payload = {
                "model": test_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
                "temperature": 0.1
            }

            t0 = time.monotonic()
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=6) as resp:
                    lat = int((time.monotonic() - t0) * 1000)
                    if resp.status == 200:
                        res = {"status": "200_OK", "latency_ms": lat, "message": f"Conexión exitosa ({lat}ms)"}
                        self.log_signal.emit(f"  🟢 {name}: 200 OK ({lat} ms)")
                    else:
                        res = {"status": f"HTTP_{resp.status}", "latency_ms": lat, "message": f"Status {resp.status}"}
                        self.log_signal.emit(f"  🟡 {name}: HTTP {resp.status} ({lat} ms)")
            except urllib.error.HTTPError as e:
                lat = int((time.monotonic() - t0) * 1000)
                if e.code == 429:
                    res = {"status": "429_LIMIT", "latency_ms": lat, "message": "Rate limit / Cuota"}
                elif e.code in (401, 403):
                    res = {"status": "AUTH_ERR", "latency_ms": lat, "message": f"Clave Inválida / Error {e.code}"}
                elif e.code == 404:
                    res = {"status": "NOT_FOUND", "latency_ms": lat, "message": "Endpoint no encontrado (404)"}
                else:
                    res = {"status": f"HTTP_{e.code}", "latency_ms": lat, "message": f"HTTP {e.code}"}
                self.log_signal.emit(f"  🔴 {name}: {res['message']} ({lat} ms)")
            except Exception as e:
                lat = int((time.monotonic() - t0) * 1000)
                res = {"status": "TIMEOUT", "latency_ms": lat, "message": str(e)[:35]}
                self.log_signal.emit(f"  ⚠️ {name}: {res['message']}")

            self.api_tested.emit(api_id, res)

        if not self.is_cancelled():
            self.log_signal.emit("✅ Prueba de conexión de APIs finalizada.")
            self.finished_signal.emit()


class PropagateAllWorker(CancellableThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict)

    def __init__(self, apis: List[Dict[str, Any]]):
        super().__init__()
        self.apis = list(apis)

    def _backup_file(self, path: str):
        if os.path.exists(path):
            try:
                shutil.copy2(path, f"{path}.bak")
            except Exception:
                pass

    def run(self):
        self.log_signal.emit("⚡ Iniciando propagación unificada 1-Clic hacia todos los agentes del ecosistema...")
        results = {}

        # 1. OpenCode (~/.config/opencode/opencode.jsonc)
        try:
            self._backup_file(OPENCODE_CONFIG)
            existing_mcp = {}
            if os.path.exists(OPENCODE_CONFIG):
                try:
                    with open(OPENCODE_CONFIG, "r", encoding="utf-8") as f:
                        old_json = json.load(f)
                        existing_mcp = old_json.get("mcp", {})
                except Exception:
                    pass

            opencode_providers = {}
            for api in self.apis:
                if not api.get("enabled", True):
                    continue
                prov = api.get("provider", "custom")
                acc_tag = api.get("account_tag", "C1")
                env_k = api.get("env_key", "")
                base_u = api.get("base_url", "")
                test_m = api.get("test_model", "default")

                # Identificador único de proveedor en OpenCode
                prov_key = f"{prov}_{acc_tag.lower()}" if acc_tag not in ("C1", "Direct", "Principal", "") else prov

                npm_pkg = "@ai-sdk/openai"
                if prov == "google":
                    npm_pkg = "@ai-sdk/google"
                elif prov == "mistral":
                    npm_pkg = "@ai-sdk/mistral"

                opts = {}
                if base_u:
                    opts["baseURL"] = base_u
                if env_k:
                    opts["apiKey"] = f"{{env:{env_k}}}"

                badge = get_account_badge_label(acc_tag)
                
                # Construir mapa de modelos enriquecido por proveedor
                models_dict = {test_m: {"name": f"{badge} [{prov.upper()}] {test_m}"}}
                if prov == "deepseek":
                    models_dict["deepseek-chat"] = {"name": f"{badge} DeepSeek Chat V3"}
                    models_dict["deepseek-reasoner"] = {"name": f"{badge} DeepSeek Reasoner R1"}
                elif prov == "openrouter":
                    models_dict = {
                        "openrouter/auto": {"name": f"{badge} OpenRouter Auto"},
                        "openrouter/free": {"name": f"{badge} OpenRouter Free"},
                        "meta-llama/llama-3.3-70b-instruct:free": {"name": f"{badge} Llama 3.3 70B (Free)"},
                        "qwen/qwen-2.5-coder-32b-instruct:free": {"name": f"{badge} Qwen 2.5 Coder (Free)"},
                        "deepseek/deepseek-r1:free": {"name": f"{badge} DeepSeek R1 (Free)"},
                        "google/gemini-2.0-flash-exp:free": {"name": f"{badge} Gemini 2.0 Flash (Free)"},
                        "minimax/minimax-m3:free": {"name": f"{badge} MiniMax M3 (Frontier)"},
                        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": {"name": f"{badge} Nemotron 3 Nano"},
                        "z-ai/glm-5.2:free": {"name": f"{badge} GLM 5.2 (Frontier)"},
                        "poolside/laguna-s-2.1:free": {"name": f"{badge} Laguna S 2.1 (Code)"}
                    }

                opencode_providers[prov_key] = {
                    "npm": npm_pkg,
                    "name": f"{badge} {api.get('name', prov)}",
                    "options": opts,
                    "models": models_dict
                }

            opencode_cfg = {
                "$schema": "https://opencode.ai/config.json",
                "model": "google/gemini-3.7-flash",
                "small_model": "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "provider": opencode_providers
            }
            if existing_mcp:
                opencode_cfg["mcp"] = existing_mcp

            os.makedirs(os.path.dirname(OPENCODE_CONFIG), exist_ok=True)
            atomic_json_write(OPENCODE_CONFIG, opencode_cfg)
            results["OpenCode"] = True
            self.log_signal.emit(f"  ✅ OpenCode sincronizado exitosamente ({len(opencode_providers)} proveedores/cuentas).")
        except Exception as e:
            results["OpenCode"] = False
            self.log_signal.emit(f"  ❌ Error en OpenCode: {e}")

        # 2. Hermes Agent (~/.hermes/config.yaml & cache)
        try:
            self._backup_file(HERMES_CONFIG)
            providers_yaml = []
            for api in self.apis:
                if not api.get("enabled", True):
                    continue
                prov = api.get("provider", "custom")
                acc_tag = api.get("account_tag", "C1")
                env_k = api.get("env_key", "")
                base_u = api.get("base_url", "")
                tm = api.get("test_model", "default")
                prov_key = f"{prov}_{acc_tag.lower()}" if acc_tag not in ("C1", "Direct", "Principal", "") else prov

                if prov == "deepseek":
                    model_lines = "      - deepseek-chat\n      - deepseek-reasoner"
                elif prov == "openrouter":
                    model_lines = """      - openrouter/auto
      - openrouter/free
      - meta-llama/llama-3.3-70b-instruct:free
      - qwen/qwen-2.5-coder-32b-instruct:free
      - deepseek/deepseek-r1:free
      - google/gemini-2.0-flash-exp:free
      - minimax/minimax-m3:free
      - nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
      - z-ai/glm-5.2:free
      - poolside/laguna-s-2.1:free"""
                else:
                    model_lines = f"      - {tm}"

                providers_yaml.append(f"""  {prov_key}:
    name: "{api.get('name', prov)}"
    env_key: {env_k}
    base_url: {base_u}
    api: openai-completions
    models:
{model_lines}""")

            hermes_content = f"""model:
  default: gemini-3.7-flash
  provider: google
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/
providers:
{chr(10).join(providers_yaml)}
database:
  journal_mode: wal
runtime:
  nofile_soft_limit: 4096
_config_version: 40
fallback_model:
  provider: openrouter
  model: minimax/minimax-m3:free
"""
            os.makedirs(os.path.dirname(HERMES_CONFIG), exist_ok=True)
            with open(HERMES_CONFIG, "w", encoding="utf-8") as f:
                f.write(hermes_content)

            hermes_clean_cache = {
                "google": {"fp": "google-curated-v3", "at": time.time(), "models": ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemma-4-31b-it"]},
                "openrouter": {"fp": "openrouter-curated-v3", "at": time.time(), "models": ["openrouter/auto", "openrouter/free", "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "deepseek/deepseek-r1:free", "google/gemini-2.0-flash-exp:free", "minimax/minimax-m3:free", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "z-ai/glm-5.2:free", "poolside/laguna-s-2.1:free"]},
                "nvidia": {"fp": "nvidia-curated-v3", "at": time.time(), "models": ["deepseek-ai/deepseek-v4-flash-0731", "moonshotai/kimi-k3", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"]},
                "mistral": {"fp": "mistral-curated-v3", "at": time.time(), "models": ["codestral-latest"]},
                "deepseek": {"fp": "deepseek-curated-v3", "at": time.time(), "models": ["deepseek-chat", "deepseek-reasoner"]}
            }
            atomic_json_write(HERMES_CACHE, hermes_clean_cache)

            results["Hermes"] = True
            self.log_signal.emit("  ✅ Hermes Agent sincronizado y purgado exitosamente.")
        except Exception as e:
            results["Hermes"] = False
            self.log_signal.emit(f"  ❌ Error en Hermes: {e}")

        # 3. Zed Editor (~/.config/zed/settings.json)
        try:
            self._backup_file(ZED_CONFIG)
            if os.path.exists(ZED_CONFIG):
                with open(ZED_CONFIG, "r", encoding="utf-8") as f:
                    zed_data = json.load(f)
            else:
                zed_data = {}

            if "agent" not in zed_data:
                zed_data["agent"] = {}

            zed_data["agent"]["default_model"] = {
                "effort": "high",
                "enable_thinking": True,
                "provider": "openrouter",
                "model": "minimax/minimax-m3:free"
            }
            os.makedirs(os.path.dirname(ZED_CONFIG), exist_ok=True)
            with open(ZED_CONFIG, "w", encoding="utf-8") as f:
                json.dump(zed_data, f, indent=2)
            results["Zed"] = True
            self.log_signal.emit("  ✅ Zed Editor sincronizado exitosamente.")
        except Exception as e:
            results["Zed"] = False
            self.log_signal.emit(f"  ❌ Error en Zed: {e}")

        # 4. Sincronización .env y Custom APIs Cache
        try:
            sanitized_list = [sanitize_api_for_disk(a) for a in self.apis]
            atomic_json_write(APIS_CONFIG_FILE, sanitized_list)
            results["EnvSync"] = True
            self.log_signal.emit(f"  ✅ Configuración persistida en caché segura: {APIS_CONFIG_FILE}")
        except Exception as e:
            results["EnvSync"] = False
            self.log_signal.emit(f"  ❌ Error persistiendo configuración: {e}")

        # 5. Generación de Script de Réplica de Respaldo
        try:
            os.makedirs(os.path.dirname(APIS_CONFIG_FILE), exist_ok=True)
            export_script_path = os.path.join(WORKSPACE_ROOT, "cache", "sync_remote_node.sh")
            export_lines = [
                "#!/usr/bin/env bash",
                "# Script generado automáticamente por FloydIA Suite para réplica segura en nodo remoto",
                "set -euo pipefail",
                'REMOTE_HOST="${REMOTE_HOST:-127.0.0.1}"',
                'REMOTE_USER="${REMOTE_USER:-$USER}"',
                'echo "🚀 Sincronizando configuraciones de agentes hacia nodo remoto ($REMOTE_HOST)..."',
                'rsync -avz --inplace ~/.config/opencode/opencode.jsonc "$REMOTE_USER@$REMOTE_HOST:~/.config/opencode/opencode.jsonc" || true',
                'rsync -avz --inplace ~/.hermes/config.yaml "$REMOTE_USER@$REMOTE_HOST:~/.hermes/config.yaml" || true',
                'echo "✅ Sincronización hacia nodo remoto completada."'
            ]
            with open(export_script_path, "w", encoding="utf-8") as f:
                f.write("\n".join(export_lines) + "\n")
            os.chmod(export_script_path, 0o755)
            results["Remote_Script"] = True
            self.log_signal.emit(f"  ✅ Script de réplica generado: {export_script_path}")
        except Exception as e:
            results["Remote_Script"] = False
            self.log_signal.emit(f"  ⚠️ Aviso generando script de réplica: {e}")

        self.finished_signal.emit(results)


class ApiEditDialog(QDialog):
    """Diálogo de configuración y edición de API con selector explícito de Cuenta [C1..C8]."""
    def __init__(self, api_data: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.is_edit = api_data is not None
        self.api_data = dict(api_data) if api_data else {}
        self.setWindowTitle("✏️ Editar API / Endpoint" if self.is_edit else "➕ Añadir Nueva API / Endpoint Multi-Cuenta")
        self.setFixedWidth(600)
        self.setStyleSheet(f"""
            QDialog {{ background-color: #070D14; color: #F1F5F9; font-family: 'Inter', sans-serif; }}
            QLabel {{ color: #E2E8F0; font-size: 11px; font-weight: bold; }}
            QLineEdit, QComboBox, QPlainTextEdit {{
                background-color: #0B121E;
                border: 1px solid #1E293B;
                border-radius: 6px;
                padding: 6px 10px;
                color: #F1F5F9;
                font-size: 11px;
            }}
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
                border: 1px solid {COLOR_PRIMARY_CYAN};
            }}
            QCheckBox {{ color: #CBD5E1; font-size: 11px; }}
            QPushButton#PrimaryBtn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00F5D4, stop:1 #00BBF9);
                color: #050911;
                font-weight: 700;
                font-size: 12px;
                border-radius: 6px;
                padding: 7px 16px;
            }}
            QPushButton#SecondaryBtn {{
                background-color: #1E293B;
                color: #F1F5F9;
                border: 1px solid #334155;
                border-radius: 6px;
                font-size: 11px;
                padding: 7px 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl_title = QLabel("Configuración de API & Proveedor LLM (Multi-Cuenta)")
        lbl_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        layout.addWidget(lbl_title)

        grid = QGridLayout()
        grid.setSpacing(10)

        # 1. Preset / Proveedor
        grid.addWidget(QLabel("Proveedor / Preset:"), 0, 0)
        self.combo_provider = QComboBox()
        self.combo_provider.addItems([
            "Google AI Studio (google)",
            "NVIDIA NIM (nvidia)",
            "DeepSeek Direct (deepseek)",
            "Mistral AI (mistral)",
            "OpenRouter (openrouter)",
            "Groq Cloud (groq)",
            "Z.AI GLM (zai)",
            "Anthropic Claude (anthropic)",
            "OpenAI Direct (openai)",
            "Ollama Local (ollama)",
            "Personalizado / Custom (custom)"
        ])
        self.combo_provider.currentIndexChanged.connect(self.on_preset_or_account_changed)
        grid.addWidget(self.combo_provider, 0, 1)

        # 2. Selector de Cuenta / Instancia [C1..C8]
        grid.addWidget(QLabel("Cuenta / Instancia [Tag]:"), 1, 0)
        acc_box = QHBoxLayout()
        self.combo_account_tag = QComboBox()
        self.combo_account_tag.setEditable(True)
        self.combo_account_tag.addItems(["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "Direct", "Local", "Principal", "Backup", "Custom"])
        self.combo_account_tag.currentTextChanged.connect(self.on_preset_or_account_changed)
        acc_box.addWidget(self.combo_account_tag)

        self.lbl_tag_preview = QLabel("[C1]")
        self.lbl_tag_preview.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.lbl_tag_preview.setStyleSheet(f"background-color: #10283D; color: {COLOR_PRIMARY_CYAN}; border-radius: 4px; padding: 3px 8px;")
        acc_box.addWidget(self.lbl_tag_preview)
        grid.addLayout(acc_box, 1, 1)

        # 3. Nombre Descriptivo
        grid.addWidget(QLabel("Nombre Descriptivo:"), 2, 0)
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Ej. Google AI Studio Pro [C1]")
        grid.addWidget(self.txt_name, 2, 1)

        # 4. Base URL
        grid.addWidget(QLabel("Base URL (API Endpoint):"), 3, 0)
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("https://generativelanguage.googleapis.com/v1beta/openai")
        grid.addWidget(self.txt_url, 3, 1)

        # 5. Variable de Entorno (.env)
        grid.addWidget(QLabel("Variable .env Asociada:"), 4, 0)
        self.txt_env_key = QLineEdit()
        self.txt_env_key.setPlaceholderText("Ej. C1_GOOGLE_AISTUDIO")
        grid.addWidget(self.txt_env_key, 4, 1)

        # 6. API Key
        grid.addWidget(QLabel("Clave API (API Key):"), 5, 0)
        key_box = QHBoxLayout()
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_api_key.setPlaceholderText("•••••••• (opcional si se lee de .env)")
        key_box.addWidget(self.txt_api_key)

        btn_toggle_echo = QPushButton("👁️")
        btn_toggle_echo.setFixedWidth(36)
        btn_toggle_echo.clicked.connect(self.toggle_key_visibility)
        key_box.addWidget(btn_toggle_echo)
        grid.addLayout(key_box, 5, 1)

        # 7. Modelo de Prueba
        grid.addWidget(QLabel("Modelo de Test / Ping:"), 6, 0)
        self.txt_model = QLineEdit()
        self.txt_model.setPlaceholderText("Ej. gemini-3.7-flash")
        grid.addWidget(self.txt_model, 6, 1)

        # 8. Tipo de Auth
        grid.addWidget(QLabel("Tipo de Autenticación:"), 7, 0)
        self.combo_auth = QComboBox()
        self.combo_auth.addItems(["Bearer", "x-api-key", "None"])
        grid.addWidget(self.combo_auth, 7, 1)

        # 9. Switch Habilitada
        self.chk_enabled = QCheckBox("API Activa e Incluida en Sondeos / Propagación")
        self.chk_enabled.setChecked(True)
        grid.addWidget(self.chk_enabled, 8, 1)

        layout.addLayout(grid)

        # Botones de Acción
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("SecondaryBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_save = QPushButton("💾 Guardar API")
        btn_save.setObjectName("PrimaryBtn")
        btn_save.clicked.connect(self.save_and_accept)
        btn_box.addWidget(btn_save)

        layout.addLayout(btn_box)

        if self.is_edit:
            self.load_data()
        else:
            self.on_preset_or_account_changed()

    def toggle_key_visibility(self):
        if self.txt_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)

    def get_selected_provider(self) -> str:
        prov_text = self.combo_provider.currentText()
        if "(" in prov_text and ")" in prov_text:
            return prov_text.split("(")[1].split(")")[0].strip().lower()
        return "custom"

    def on_preset_or_account_changed(self, *args):
        prov = self.get_selected_provider()
        tag = self.combo_account_tag.currentText().strip() or "C1"
        badge_lbl = get_account_badge_label(tag)
        color = get_provider_color(prov)
        self.lbl_tag_preview.setText(badge_lbl)
        self.lbl_tag_preview.setStyleSheet(f"background-color: #10283D; color: {color}; border: 1px solid {color}; border-radius: 4px; padding: 3px 8px; font-weight: bold;")

        if not self.is_edit:
            # Presets por proveedor
            presets = {
                "google": ("Google AI Studio", f"{tag}_GOOGLE_AISTUDIO", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.7-flash", "Bearer"),
                "nvidia": ("NVIDIA NIM Dedicated", f"{tag}_NVIDIA" if tag != "C7" else "C7_NVIDIA", "https://integrate.api.nvidia.com/v1", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "Bearer"),
                "deepseek": ("DeepSeek Direct", f"{tag}_DEEPSEEK" if tag != "Direct" else "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat", "Bearer"),
                "mistral": ("Mistral AI / Codestral", f"{tag}_MISTRAL", "https://api.mistral.ai/v1", "codestral-latest", "Bearer"),
                "openrouter": ("OpenRouter Global Hub", f"{tag}_OPENROUTER" if tag != "C7" else "C7_OPENROUTER_OPENCODE_HP15", "https://openrouter.ai/api/v1", "openrouter/auto", "Bearer"),
                "groq": ("Groq LPU Cloud", f"{tag}_GROQ", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "Bearer"),
                "zai": ("Z.AI GLM Cloud", f"{tag}_Z_AI", "https://api.z.ai/v1", "glm-4-plus", "Bearer"),
                "anthropic": ("Anthropic Claude API", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-3-5-sonnet-20241022", "x-api-key"),
                "openai": ("OpenAI Direct API", "OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini", "Bearer"),
                "ollama": ("Ollama Local Homelab", f"{tag}_OLLAMA", "http://localhost:11434/v1", "llama3.2:3b", "None"),
            }
            if prov in presets:
                name_base, env_k, url, model, auth = presets[prov]
                self.txt_name.setText(f"{name_base} [{tag}]")
                self.txt_env_key.setText(env_k)
                self.txt_url.setText(url)
                self.txt_model.setText(model)
                self.combo_auth.setCurrentText(auth)

    def load_data(self):
        self.txt_name.setText(self.api_data.get("name", ""))
        self.txt_url.setText(self.api_data.get("base_url", ""))
        self.txt_env_key.setText(self.api_data.get("env_key", ""))
        self.txt_api_key.setText(self.api_data.get("api_key", ""))
        self.txt_model.setText(self.api_data.get("test_model", ""))
        self.combo_auth.setCurrentText(self.api_data.get("auth_type", "Bearer"))
        self.chk_enabled.setChecked(self.api_data.get("enabled", True))
        
        tag = self.api_data.get("account_tag", "C1")
        self.combo_account_tag.setCurrentText(tag)

        prov = self.api_data.get("provider", "custom")
        for i in range(self.combo_provider.count()):
            if f"({prov})" in self.combo_provider.itemText(i):
                self.combo_provider.setCurrentIndex(i)
                break

    def save_and_accept(self):
        name = self.txt_name.text().strip()
        url = self.txt_url.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "Campos Incompletos", "Por favor ingresa al menos el Nombre y la Base URL de la API.")
            return

        prov = self.get_selected_provider()
        tag = self.combo_account_tag.currentText().strip() or "C1"
        
        # Clave primaria unívoca {provider}_{account_tag}_{model_or_alias}
        tag_clean = tag.lower().replace("[", "").replace("]", "").replace(" ", "_")
        api_id = self.api_data.get("id") or f"{prov}_{tag_clean}"

        self.api_data = {
            "id": api_id,
            "name": name,
            "provider": prov,
            "account_tag": tag,
            "env_key": self.txt_env_key.text().strip(),
            "base_url": url,
            "api_key": self.txt_api_key.text().strip(),
            "test_model": self.txt_model.text().strip() or "default",
            "auth_type": self.combo_auth.currentText(),
            "enabled": self.chk_enabled.isChecked(),
            "notes": self.api_data.get("notes", "")
        }
        self.accept()

    def get_api_data(self) -> Dict[str, Any]:
        return self.api_data


class DeepSeekExportDialog(QDialog):
    """Modal de inspección, copia y propagación focalizada de configuraciones DeepSeek."""
    def __init__(self, deepseek_apis: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.deepseek_apis = deepseek_apis
        self.setWindowTitle("📤 Exportar & Propagar Configuración DeepSeek (C1..C7)")
        self.resize(650, 480)
        self.setStyleSheet(f"""
            QDialog {{ background-color: #070D14; color: #F1F5F9; font-family: 'Inter', sans-serif; }}
            QLabel {{ color: #E2E8F0; font-size: 12px; }}
            QPlainTextEdit {{
                background-color: #0B121E;
                border: 1px solid #1E293B;
                border-radius: 6px;
                padding: 10px;
                color: #38BDF8;
                font-family: 'Monospace', monospace;
                font-size: 11px;
            }}
            QPushButton#PrimaryBtn {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38BDF8, stop:1 #0284C7);
                color: #050911;
                font-weight: 700;
                border-radius: 6px;
                padding: 8px 16px;
            }}
            QPushButton#SecondaryBtn {{
                background-color: #1E293B;
                color: #F1F5F9;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        lbl_t = QLabel("Configuración Multi-Cuenta DeepSeek (OpenCode / Hermes / Zed)")
        lbl_t.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        lbl_t.setStyleSheet("color: #38BDF8;")
        layout.addWidget(lbl_t)

        lbl_desc = QLabel(f"Se detectaron {len(self.deepseek_apis)} cuentas de DeepSeek configuradas. Puedes copiar el payload JSON/YAML o propagarlo directamente a tus agentes.")
        lbl_desc.setWordWrap(True)
        layout.addWidget(lbl_desc)

        # Generar Payload JSON / YAML
        self.payload_dict = {
            "deepseek_fleet": [
                {
                    "id": a.get("id"),
                    "account_tag": a.get("account_tag", "C1"),
                    "env_key": a.get("env_key"),
                    "base_url": a.get("base_url"),
                    "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"]
                }
                for a in self.deepseek_apis
            ]
        }
        self.payload_text = json.dumps(self.payload_dict, indent=2)

        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setPlainText(self.payload_text)
        self.txt_preview.setReadOnly(True)
        layout.addWidget(self.txt_preview)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("📋 Copiar JSON")
        btn_copy.setObjectName("SecondaryBtn")
        btn_copy.clicked.connect(self.copy_json)
        btn_row.addWidget(btn_copy)

        btn_copy_yaml = QPushButton("📋 Copiar YAML (Hermes)")
        btn_copy_yaml.setObjectName("SecondaryBtn")
        btn_copy_yaml.clicked.connect(self.copy_yaml)
        btn_row.addWidget(btn_copy_yaml)

        btn_row.addStretch()

        btn_close = QPushButton("Cerrar")
        btn_close.setObjectName("SecondaryBtn")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    def copy_json(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.payload_text)
            QMessageBox.information(self, "Copiado", "✅ Configuración JSON de DeepSeek copiada al portapapeles.")

    def copy_yaml(self):
        yaml_lines = ["providers:"]
        for a in self.deepseek_apis:
            tag = a.get("account_tag", "C1").lower()
            yaml_lines.append(f"""  deepseek_{tag}:
    name: "{a.get('name')}"
    env_key: {a.get('env_key')}
    base_url: {a.get('base_url')}
    api: openai-completions
    models:
      - deepseek-chat
      - deepseek-reasoner""")
        yaml_text = "\n".join(yaml_lines)
        cb = QApplication.clipboard()
        if cb:
            cb.setText(yaml_text)
            QMessageBox.information(self, "Copiado", "✅ Configuración YAML de DeepSeek copiada al portapapeles.")


class TabApiManager(QWidget):
    def __init__(self):
        super().__init__()
        self.apis: List[Dict[str, Any]] = []
        self.ping_worker: Optional[ApiPingWorker] = None
        self.propagate_worker: Optional[PropagateAllWorker] = None
        self.env_map = load_env_vars()
        self.init_data()
        self.init_ui()

    def init_data(self):
        loaded_apis = []
        if os.path.exists(APIS_CONFIG_FILE):
            try:
                with open(APIS_CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded_apis = json.load(f)
            except Exception:
                loaded_apis = []

        existing_ids = {a.get("id") for a in loaded_apis if a.get("id")}
        self.apis = list(loaded_apis) if loaded_apis else []

        # Incorporar de forma no destructiva las cuentas multi-cuenta canónicas que falten
        for def_api in DEFAULT_APIS:
            if def_api.get("id") not in existing_ids:
                self.apis.append(dict(def_api))
                existing_ids.add(def_api.get("id"))

        # Completar API keys desde .env
        for api in self.apis:
            env_k = api.get("env_key")
            if env_k and env_k in self.env_map and not api.get("api_key"):
                api["api_key"] = self.env_map[env_k]

    def save_apis(self):
        sanitized = [sanitize_api_for_disk(a) for a in self.apis]
        atomic_json_write(APIS_CONFIG_FILE, sanitized)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ── 1. Top Bar: Título & Botones Principales ──────────────────────────
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        title = QLabel("🔑 Gestor de APIs, Endpoints & Propagación Agéntica")
        title.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")

        subtitle = QLabel("Gestión centralizada multi-cuenta [C1..C8] con propagación 1-clic a OpenCode, Hermes, Zed y .env")
        subtitle.setFont(QFont("Inter", 9))
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_bar.addLayout(title_box)
        top_bar.addStretch()

        self.btn_add_api = QPushButton("➕ Añadir API")
        self.btn_add_api.setObjectName("PrimaryBtn")
        self.btn_add_api.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_api.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self.btn_add_api.clicked.connect(self.add_api_dialog)
        top_bar.addWidget(self.btn_add_api)

        self.btn_test_all = QPushButton("⚡ Probar Conexión (Ping)")
        self.btn_test_all.setObjectName("SecondaryBtn")
        self.btn_test_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_all.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self.btn_test_all.clicked.connect(self.ping_all_apis)
        top_bar.addWidget(self.btn_test_all)

        self.btn_propagate_all = QPushButton("🚀 PROPAGAR A TODOS LOS AGENTES (1-CLIC)")
        self.btn_propagate_all.setObjectName("ActionSyncBtn")
        self.btn_propagate_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_propagate_all.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        self.btn_propagate_all.clicked.connect(self.propagate_all_agents)
        top_bar.addWidget(self.btn_propagate_all)

        layout.addLayout(top_bar)

        # ── 2. KPI Cards ──────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)

        self.card_total = self.create_kpi_card("TOTAL APIS", f"{len(self.apis)} Registradas", "Proveedores configurados", "#38BDF8")
        active_cnt = sum(1 for a in self.apis if a.get("enabled", True))
        self.card_active = self.create_kpi_card("APIS ACTIVAS", f"{active_cnt} / {len(self.apis)}", "Disponibles para agentes", "#10B981")
        keys_cnt = sum(1 for a in self.apis if a.get("api_key") or (a.get("env_key") and a.get("env_key") in self.env_map))
        self.card_keys = self.create_kpi_card("CON CLAVE .ENV", f"{keys_cnt} Autenticadas", "Listas para producción", "#818CF8")
        self.card_health = self.create_kpi_card("ESTADO CONEXIÓN", "Listo", "Presiona Probar Conexión", "#F59E0B")

        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_active)
        kpi_row.addWidget(self.card_keys)
        kpi_row.addWidget(self.card_health)
        layout.addLayout(kpi_row)

        # ── 3. Barra de Búsqueda, Filtros Multi-Cuenta & Selección Masiva ──────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Buscar por nombre, cuenta [C1], proveedor, URL o variable .env...")
        self.txt_search.setMinimumWidth(260)
        self.txt_search.textChanged.connect(self.populate_table)
        filter_bar.addWidget(self.txt_search)

        # Filtro de Cuentas [C1..C8]
        self.combo_account_filter = QComboBox()
        self.combo_account_filter.addItems([
            "Todas las Cuentas",
            "Solo [C1]",
            "Solo [C2]",
            "Solo [C3]",
            "Solo [C4]",
            "Solo [C5]",
            "Solo [C6]",
            "Solo [C7]",
            "Solo Direct / Local"
        ])
        self.combo_account_filter.currentIndexChanged.connect(self.populate_table)
        filter_bar.addWidget(self.combo_account_filter)

        # Filtro de Estado
        self.combo_filter_status = QComboBox()
        self.combo_filter_status.addItems(["Todos los Estados", "Solo Activas", "Solo Desactivadas", "Con API Key", "Sin API Key"])
        self.combo_filter_status.currentIndexChanged.connect(self.populate_table)
        filter_bar.addWidget(self.combo_filter_status)

        # Botones de Selección Masiva
        self.btn_select_all = QPushButton("☑️ Marcar Todos")
        self.btn_select_all.setObjectName("SecondaryBtn")
        self.btn_select_all.clicked.connect(lambda: self.set_all_enabled(True))
        filter_bar.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("⬜ Desmarcar")
        self.btn_deselect_all.setObjectName("SecondaryBtn")
        self.btn_deselect_all.clicked.connect(lambda: self.set_all_enabled(False))
        filter_bar.addWidget(self.btn_deselect_all)

        self.lbl_table_count = QLabel(f"APIs: {len(self.apis)}")
        self.lbl_table_count.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.lbl_table_count.setStyleSheet(f"color: {COLOR_SECONDARY_BLUE};")
        filter_bar.addWidget(self.lbl_table_count)

        filter_bar.addStretch()

        btn_auto_cols = QPushButton("↔️ Ajustar Ancho")
        btn_auto_cols.setObjectName("SecondaryBtn")
        btn_auto_cols.clicked.connect(self.auto_resize_columns)
        filter_bar.addWidget(btn_auto_cols)

        btn_reload = QPushButton("↺ Recargar .env")
        btn_reload.setObjectName("SecondaryBtn")
        btn_reload.clicked.connect(self.reload_from_env)
        filter_bar.addWidget(btn_reload)

        layout.addLayout(filter_bar)

        # ── 4. Splitter: Tabla de APIs y Consola de Sincronización ────────────
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Tabla Principal
        table_frame = QFrame()
        table_frame.setProperty("class", "CardFrame")
        table_lay = QVBoxLayout(table_frame)
        table_lay.setContentsMargins(4, 4, 4, 4)

        self.table_apis = QTableWidget()
        self.table_apis.setColumnCount(8)
        self.table_apis.setHorizontalHeaderLabels([
            "Activa", "Cuenta / Nombre", "Variable .env", "Base URL", "API Key (Enmascarada)", "Modelo Test", "Estado / Ping", "Acciones"
        ])
        self.table_apis.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_apis.setColumnWidth(0, 56)
        for i in range(1, 8):
            self.table_apis.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        self.table_apis.setColumnWidth(1, 210)
        self.table_apis.setColumnWidth(2, 160)
        self.table_apis.setColumnWidth(3, 210)
        self.table_apis.setColumnWidth(4, 140)
        self.table_apis.setColumnWidth(5, 140)
        self.table_apis.setColumnWidth(6, 130)
        self.table_apis.setColumnWidth(7, 130)

        self.table_apis.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_apis.setSortingEnabled(True)

        table_lay.addWidget(self.table_apis)
        splitter.addWidget(table_frame)

        # Panel Inferior: Consola y Acciones de Agentes
        bottom_frame = QFrame()
        bottom_frame.setProperty("class", "CardFrame")
        bottom_lay = QVBoxLayout(bottom_frame)
        bottom_lay.setContentsMargins(8, 8, 8, 8)
        bottom_lay.setSpacing(6)

        # Fila de Botones Rápidos por Agente
        agents_row = QHBoxLayout()
        agents_row.setSpacing(6)

        lbl_agents = QLabel("Sincronización Focalizada:")
        lbl_agents.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        lbl_agents.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        agents_row.addWidget(lbl_agents)

        btn_sync_opencode = QPushButton("⚡ OpenCode")
        btn_sync_opencode.setObjectName("SecondaryBtn")
        btn_sync_opencode.clicked.connect(lambda: self.sync_single_target("opencode"))
        agents_row.addWidget(btn_sync_opencode)

        btn_sync_hermes = QPushButton("🪽 Hermes Agent")
        btn_sync_hermes.setObjectName("SecondaryBtn")
        btn_sync_hermes.clicked.connect(lambda: self.sync_single_target("hermes"))
        agents_row.addWidget(btn_sync_hermes)

        btn_sync_zed = QPushButton("📝 Zed Editor")
        btn_sync_zed.setObjectName("SecondaryBtn")
        btn_sync_zed.clicked.connect(lambda: self.sync_single_target("zed"))
        agents_row.addWidget(btn_sync_zed)

        btn_sync_hp45 = QPushButton("💻 Nodo Remoto")
        btn_sync_hp45.setObjectName("SecondaryBtn")
        btn_sync_hp45.setToolTip("Ejecuta réplica rsync hacia el nodo remoto configurado")
        btn_sync_hp45.clicked.connect(lambda: self.sync_single_target("hp45"))
        agents_row.addWidget(btn_sync_hp45)

        # Botones DeepSeek dedicados
        btn_deepseek_export = QPushButton("📤 DeepSeek (C1..C7)")
        btn_deepseek_export.setObjectName("DeepSeekActionBtn")
        btn_deepseek_export.clicked.connect(self.export_deepseek_dialog)
        agents_row.addWidget(btn_deepseek_export)

        btn_deepseek_copy = QPushButton("📋 Copiar DeepSeek")
        btn_deepseek_copy.setObjectName("SecondaryBtn")
        btn_deepseek_copy.clicked.connect(self.copy_deepseek_fast)
        agents_row.addWidget(btn_deepseek_copy)

        agents_row.addStretch()
        bottom_lay.addLayout(agents_row)

        # Consola de Propagación
        lbl_log = QLabel("Bitácora de Propagación & SRE:")
        lbl_log.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        bottom_lay.addWidget(lbl_log)

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #070D14; border: 1px solid #1E293B; border-radius: 6px; font-family: monospace; font-size: 10px; color: #E2E8F0;")
        bottom_lay.addWidget(self.log_console)

        splitter.addWidget(bottom_frame)
        splitter.setSizes([420, 220])
        layout.addWidget(splitter, stretch=1)

        self.populate_table()
        self.log("✅ Gestor de APIs Multi-Cuenta cargado. Todas las cuentas [C1..C8] inicializadas.")

    def create_kpi_card(self, title: str, main_val: str, subtitle: str, color_accent: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "CardFrame")
        card.setStyleSheet("background-color: #070D14; border: 1px solid #1E293B; border-radius: 8px; padding: 6px;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        lbl_t.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lay.addWidget(lbl_t)

        lbl_v = QLabel(main_val)
        lbl_v.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        lbl_v.setStyleSheet(f"color: {color_accent};")
        lbl_v.setObjectName("ValLabel")
        lay.addWidget(lbl_v)

        lbl_s = QLabel(subtitle)
        lbl_s.setFont(QFont("Inter", 8))
        lbl_s.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lbl_s.setObjectName("SubLabel")
        lay.addWidget(lbl_s)

        return card

    def update_kpi_dashboard(self):
        total = len(self.apis)
        active = sum(1 for a in self.apis if a.get("enabled", True))
        keys = sum(1 for a in self.apis if a.get("api_key") or (a.get("env_key") and a.get("env_key") in self.env_map))

        self.card_total.findChild(QLabel, "ValLabel").setText(f"{total} Registradas")
        self.card_active.findChild(QLabel, "ValLabel").setText(f"{active} / {total} Activas")
        self.card_keys.findChild(QLabel, "ValLabel").setText(f"{keys} Autenticadas")

    def log(self, text: str):
        self.log_console.appendPlainText(text)

    def auto_resize_columns(self):
        self.table_apis.resizeColumnsToContents()
        min_widths = [56, 200, 150, 190, 130, 130, 120, 120]
        for col, min_w in enumerate(min_widths):
            if self.table_apis.columnWidth(col) < min_w:
                self.table_apis.setColumnWidth(col, min_w)
        self.log("↔️ Columnas ajustadas automáticamente.")

    def reload_from_env(self):
        self.env_map = load_env_vars()
        self.init_data()
        self.populate_table()
        self.update_kpi_dashboard()
        self.log("↺ Variables de .env recargadas exitosamente.")

    def set_all_enabled(self, state: bool):
        for a in self.apis:
            a["enabled"] = state
        self.save_apis()
        self.populate_table()
        self.update_kpi_dashboard()
        st_text = "todas activadas" if state else "todas desactivadas"
        self.log(f"🔄 Selección masiva: APIs {st_text}.")

    def populate_table(self):
        query = self.txt_search.text().lower().strip()
        f_idx = self.combo_filter_status.currentIndex()
        acc_filter_text = self.combo_account_filter.currentText()

        filtered = []
        for a in self.apis:
            name = a.get("name", "").lower()
            prov = a.get("provider", "").lower()
            url = a.get("base_url", "").lower()
            env_k = a.get("env_key", "").lower()
            tag = a.get("account_tag", "C1").upper()
            has_key = bool(a.get("api_key") or (a.get("env_key") and a.get("env_key") in self.env_map))
            is_en = a.get("enabled", True)

            if query and (query not in name and query not in prov and query not in url and query not in env_k and query not in tag.lower()):
                continue

            if f_idx == 1 and not is_en:
                continue
            elif f_idx == 2 and is_en:
                continue
            elif f_idx == 3 and not has_key:
                continue
            elif f_idx == 4 and has_key:
                continue

            if acc_filter_text != "Todas las Cuentas":
                if "Solo [" in acc_filter_text:
                    expected_tag = acc_filter_text.split("[")[1].split("]")[0]
                    if tag != expected_tag:
                        continue
                elif acc_filter_text == "Solo Direct / Local":
                    if tag not in ("DIRECT", "LOCAL", "PAID"):
                        continue

            filtered.append(a)

        self.table_apis.setSortingEnabled(False)
        self.table_apis.setRowCount(len(filtered))
        self.lbl_table_count.setText(f"APIs: {len(filtered)} / {len(self.apis)}")

        for row, a in enumerate(filtered):
            api_id = a.get("id", "")
            is_enabled = a.get("enabled", True)
            prov = a.get("provider", "custom")
            tag = a.get("account_tag", "C1")
            prov_color = get_provider_color(prov)
            badge_label = get_account_badge_label(tag)

            # Col 0: Checkbox Activa
            cb = QCheckBox()
            cb.setChecked(is_enabled)
            cb.toggled.connect(lambda checked, aid=api_id: self.toggle_api_enabled(aid, checked))
            cb_container = QWidget()
            cb_lay = QHBoxLayout(cb_container)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table_apis.setCellWidget(row, 0, cb_container)

            # Col 1: Nombre / Proveedor con Badge Cromático
            name_text = f"{badge_label} {a.get('name', api_id)}"
            item_name = SortableTableWidgetItem(name_text, sort_value=f"{prov}_{tag}_{name_text.lower()}")
            item_name.setFont(QFont("Inter", 9, QFont.Weight.Bold))
            if is_enabled:
                item_name.setForeground(QColor(prov_color))
            else:
                item_name.setForeground(QColor("#64748B"))
            self.table_apis.setItem(row, 1, item_name)

            # Col 2: Variable .env
            env_k = a.get("env_key", "")
            item_env = SortableTableWidgetItem(env_k, sort_value=env_k)
            item_env.setFont(QFont("Monospace", 8))
            item_env.setForeground(QColor("#38BDF8"))
            self.table_apis.setItem(row, 2, item_env)

            # Col 3: Base URL
            url_text = a.get("base_url", "")
            item_url = SortableTableWidgetItem(url_text, sort_value=url_text)
            item_url.setFont(QFont("Inter", 8))
            item_url.setToolTip(url_text)
            self.table_apis.setItem(row, 3, item_url)

            # Col 4: API Key Enmascarada
            raw_key = a.get("api_key") or self.env_map.get(env_k, "")
            masked_key = "••••••••••••" if raw_key else "⚪ Sin Clave"
            item_key = SortableTableWidgetItem(masked_key, sort_value=bool(raw_key))
            item_key.setFont(QFont("Monospace", 8))
            item_key.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_key.setForeground(QColor("#10B981") if raw_key else QColor("#94A3B8"))
            self.table_apis.setItem(row, 4, item_key)

            # Col 5: Modelo de Test
            tm = a.get("test_model", "default")
            item_tm = SortableTableWidgetItem(tm, sort_value=tm)
            item_tm.setFont(QFont("Monospace", 8))
            self.table_apis.setItem(row, 5, item_tm)

            # Col 6: Estado / Latencia Ping
            st = a.get("last_status", "Sin probar")
            lat = a.get("last_latency", 0)
            if st == "200_OK":
                st_text = f"🟢 200 OK ({lat}ms)"
                st_color = QColor("#10B981")
                sort_rank = 1
            elif "429" in st:
                st_text = f"🟡 429 Limit"
                st_color = QColor("#F59E0B")
                sort_rank = 2
            elif st != "Sin probar":
                st_text = f"🔴 {st}"
                st_color = QColor("#EF4444")
                sort_rank = 3
            else:
                st_text = "⚪ Sin probar"
                st_color = QColor("#94A3B8")
                sort_rank = 4

            item_st = SortableTableWidgetItem(st_text, sort_value=sort_rank)
            item_st.setForeground(st_color)
            item_st.setFont(QFont("Inter", 8, QFont.Weight.Bold))
            item_st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_apis.setItem(row, 6, item_st)

            # Col 7: Acciones
            actions_widget = QWidget()
            act_lay = QHBoxLayout(actions_widget)
            act_lay.setContentsMargins(2, 2, 2, 2)
            act_lay.setSpacing(4)

            btn_test = QPushButton("⚡")
            btn_test.setToolTip("Probar conexión a esta API")
            btn_test.setFixedSize(26, 24)
            btn_test.clicked.connect(lambda _, aid=api_id: self.ping_single_api(aid))
            act_lay.addWidget(btn_test)

            btn_edit = QPushButton("✏️")
            btn_edit.setToolTip("Editar datos de esta API")
            btn_edit.setFixedSize(26, 24)
            btn_edit.clicked.connect(lambda _, aid=api_id: self.edit_api_dialog(aid))
            act_lay.addWidget(btn_edit)

            btn_del = QPushButton("🗑️")
            btn_del.setToolTip("Eliminar API")
            btn_del.setFixedSize(26, 24)
            btn_del.clicked.connect(lambda _, aid=api_id: self.delete_api(aid))
            act_lay.addWidget(btn_del)

            self.table_apis.setCellWidget(row, 7, actions_widget)

        self.table_apis.setSortingEnabled(True)

    def toggle_api_enabled(self, api_id: str, checked: bool):
        for a in self.apis:
            if a.get("id") == api_id:
                a["enabled"] = checked
                self.save_apis()
                self.update_kpi_dashboard()
                st_str = "Habilitada" if checked else "Desactivada"
                self.log(f"🔄 API '{a.get('name')}' marcada como {st_str}.")
                break

    def add_api_dialog(self):
        dlg = ApiEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_api = dlg.get_api_data()
            self.apis.append(new_api)
            self.save_apis()
            self.populate_table()
            self.update_kpi_dashboard()
            self.log(f"➕ Nueva API añadida: {new_api.get('name')}")

    def edit_api_dialog(self, api_id: str):
        target = next((a for a in self.apis if a.get("id") == api_id), None)
        if not target:
            return
        dlg = ApiEditDialog(api_data=target, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_api_data()
            for idx, a in enumerate(self.apis):
                if a.get("id") == api_id:
                    self.apis[idx] = updated
                    break
            self.save_apis()
            self.populate_table()
            self.update_kpi_dashboard()
            self.log(f"✏️ API '{updated.get('name')}' actualizada.")

    def delete_api(self, api_id: str):
        target = next((a for a in self.apis if a.get("id") == api_id), None)
        if not target:
            return
        reply = QMessageBox.question(
            self, "Confirmar Eliminación",
            f"¿Estás seguro de eliminar la API '{target.get('name')}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.apis = [a for a in self.apis if a.get("id") != api_id]
            self.save_apis()
            self.populate_table()
            self.update_kpi_dashboard()
            self.log(f"🗑️ API '{target.get('name')}' eliminada.")

    def ping_single_api(self, api_id: str):
        target = next((a for a in self.apis if a.get("id") == api_id), None)
        if not target:
            return
        self.ping_apis_list([target])

    def ping_all_apis(self):
        active_apis = [a for a in self.apis if a.get("enabled", True)]
        if not active_apis:
            active_apis = list(self.apis)
        self.ping_apis_list(active_apis)

    def ping_apis_list(self, apis: List[Dict[str, Any]]):
        if is_worker_running(self.ping_worker):
            self.log("⚠️ Ya hay una prueba de conexión en curso.")
            return

        self.btn_test_all.setEnabled(False)
        self.btn_test_all.setText("⏳ Probando...")
        self.ping_worker = ApiPingWorker(apis)
        self.ping_worker.api_tested.connect(self._on_api_tested)
        self.ping_worker.log_signal.connect(self.log)
        self.ping_worker.finished_signal.connect(self._on_ping_finished)
        self.ping_worker.finished.connect(self._on_ping_worker_cleanup)
        self.ping_worker.start()

    def _on_api_tested(self, api_id: str, res: dict):
        for a in self.apis:
            if a.get("id") == api_id:
                a["last_status"] = res.get("status")
                a["last_latency"] = res.get("latency_ms", 0)
                break
        self.populate_table()

    def _on_ping_finished(self):
        self.btn_test_all.setEnabled(True)
        self.btn_test_all.setText("⚡ Probar Conexión (Ping)")
        self.card_health.findChild(QLabel, "ValLabel").setText("Sondeo Completado")
        self.card_health.findChild(QLabel, "SubLabel").setText(f"{datetime.datetime.now().strftime('%H:%M:%S')}")

    def _on_ping_worker_cleanup(self):
        if self.ping_worker:
            self.ping_worker.deleteLater()
            self.ping_worker = None

    def propagate_all_agents(self):
        if is_worker_running(self.propagate_worker):
            self.log("⚠️ Ya hay una propagación en curso.")
            return

        self.btn_propagate_all.setEnabled(False)
        self.btn_propagate_all.setText("⏳ PROPAGANDO...")
        self.propagate_worker = PropagateAllWorker(self.apis)
        self.propagate_worker.log_signal.connect(self.log)
        self.propagate_worker.finished_signal.connect(self._on_propagate_finished)
        self.propagate_worker.finished.connect(self._on_propagate_worker_cleanup)
        self.propagate_worker.start()

    def _on_propagate_finished(self, results: dict):
        self.btn_propagate_all.setEnabled(True)
        self.btn_propagate_all.setText("🚀 PROPAGAR A TODOS LOS AGENTES (1-CLIC)")
        summary_lines = []
        for k, v in results.items():
            st = "✅ OK" if v is True else ("⚠️ Omitido" if v is None else "❌ Error")
            summary_lines.append(f"• {k}: {st}")
        summary_text = "\n".join(summary_lines)
        QMessageBox.information(
            self, "Propagación Completa",
            f"✅ Configuración de APIs multi-cuenta propagada exitosamente a todos los agentes:\n\n{summary_text}"
        )

    def _on_propagate_worker_cleanup(self):
        if self.propagate_worker:
            self.propagate_worker.deleteLater()
            self.propagate_worker = None

    def sync_single_target(self, target: str):
        if target in ("opencode", "hermes", "zed"):
            self.propagate_all_agents()
        elif target == "hp45":
            sync_script = os.path.join(CACHE_DIR, "sync_remote_node.sh")
            if os.path.exists(sync_script):
                import subprocess
                try:
                    subprocess.Popen([sync_script])
                    self.log("💻 Réplica enviada a nodo remoto en segundo plano.")
                    QMessageBox.information(self, "Nodo Remoto", "✅ Réplica enviada a nodo remoto.")
                except Exception as e:
                    self.log(f"❌ Error ejecutando script de réplica: {e}")
            else:
                QMessageBox.warning(self, "Nodo Remoto", "Script sync_remote_node.sh no encontrado en cache.")

    def export_deepseek_dialog(self):
        deepseek_list = [a for a in self.apis if a.get("provider") == "deepseek"]
        if not deepseek_list:
            QMessageBox.warning(self, "Sin Cuentas DeepSeek", "No hay cuentas de DeepSeek registradas en el Gestor de APIs.")
            return
        dlg = DeepSeekExportDialog(deepseek_list, parent=self)
        dlg.exec()

    def copy_deepseek_fast(self):
        deepseek_list = [a for a in self.apis if a.get("provider") == "deepseek"]
        if not deepseek_list:
            QMessageBox.warning(self, "Sin Cuentas DeepSeek", "No hay cuentas de DeepSeek registradas.")
            return
        payload = {
            "deepseek_providers": [
                {
                    "account": a.get("account_tag", "C1"),
                    "name": a.get("name"),
                    "env_key": a.get("env_key"),
                    "base_url": a.get("base_url"),
                    "test_model": a.get("test_model")
                }
                for a in deepseek_list
            ]
        }
        cb = QApplication.clipboard()
        if cb:
            cb.setText(json.dumps(payload, indent=2))
            self.log(f"📋 Configuración de {len(deepseek_list)} cuentas DeepSeek copiada al portapapeles.")
            QMessageBox.information(self, "DeepSeek Copiado", f"✅ {len(deepseek_list)} cuentas DeepSeek copiadas al portapapeles.")

    def cleanup(self):
        for worker in (self.ping_worker, self.propagate_worker):
            stop_worker(worker, timeout_ms=1800)
        self.ping_worker = None
        self.propagate_worker = None
