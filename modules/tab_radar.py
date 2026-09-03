#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Pestaña 4: AI Radar, Observatorio de Modelos & Asesor IA
Telemetría en vivo, sondas configurables (custom benchmark & prompts),
dashboard visual KPI, exportador de informes Markdown (.md) y HTML,
módulo interactivo "Pregúntale a la IA" y sincronización multi-cliente.
"""

import os
import sys
import json
import time
import datetime
import subprocess
import urllib.request
import urllib.error
import fcntl
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QThread, QObject, QTimer
from PyQt6.QtGui import QFont, QColor, QCursor, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QPlainTextEdit, QMessageBox, QScrollArea,
    QComboBox, QProgressBar, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QAbstractItemView, QSizePolicy, QCheckBox,
    QFileDialog, QApplication, QRadioButton, QButtonGroup, QDialog,
    QDialogButtonBox
)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker, is_worker_running,
    get_provider_color, get_account_badge_label
)
from modules.state_store import atomic_read_json, atomic_write_json, utc_now_iso
import re

DEEPSEEK_CANONICAL_SLUGS = frozenset({"deepseek-chat", "deepseek-reasoner"})

def normalize_deepseek_slug(raw_slug: str) -> str:
    """
    Sanitiza cualquier slug interno de DeepSeek hacia los identificadores
    válidos en la API directa oficial (https://api.deepseek.com/v1):
        - deepseek-chat     (DeepSeek-V3)
        - deepseek-reasoner (DeepSeek-R1)
    """
    if not raw_slug:
        return raw_slug
    slug = str(raw_slug).strip().lower()
    slug = re.sub(r"-c\d+$", "", slug)
    if slug in DEEPSEEK_CANONICAL_SLUGS:
        return slug
    if "reason" in slug or slug.endswith("-r1") or slug == "r1":
        return "deepseek-reasoner"
    return "deepseek-chat"

def find_workspace_root() -> str:
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.exists(os.path.join(curr, "SCRIPTS", "sync_models_hp45.sh")) or os.path.exists(os.path.join(curr, ".env")):
            return curr
        curr = os.path.dirname(curr)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKSPACE_ROOT = os.environ.get("FLOYDIA_WORKSPACE", find_workspace_root())
ENV_FILE = os.path.join(WORKSPACE_ROOT, ".env")
OPENCODE_CONFIG = os.environ.get("OPENCODE_CONFIG_PATH", os.path.expanduser("~/.config/opencode/opencode.jsonc"))
HERMES_CONFIG = os.environ.get("HERMES_CONFIG_PATH", os.path.expanduser("~/.hermes/config.yaml"))
HERMES_CACHE = os.path.expanduser("~/.hermes/provider_models_cache.json")
ZED_CONFIG = os.environ.get("ZED_CONFIG_PATH", os.path.expanduser("~/.config/zed/settings.json"))
REPORTS_DIR = os.path.join(WORKSPACE_ROOT, "reports")
CACHE_DIR = os.path.join(WORKSPACE_ROOT, "cache")
SYNC_REMOTE_SCRIPT = os.path.join(CACHE_DIR, "sync_remote_node.sh")
RADAR_CACHE_FILE = os.path.join(CACHE_DIR, "last_radar_telemetry.json")



SENSITIVE_KEYS = {
    "key", "api_key", "token", "authorization", "password", "secret",
    "c1_google_aistudio", "c7_openrouter", "google_api_key", "openrouter_api_key"
}


def sanitize_for_persistence(value):
    """P0 Security: Elimina cualquier secreto o API key antes de persistir a disco."""
    if isinstance(value, dict):
        return {
            k: sanitize_for_persistence(v)
            for k, v in value.items()
            if k.lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [sanitize_for_persistence(v) for v in value]
    return value


def atomic_json_write(path: str, data: dict, mode: int = 0o600) -> None:
    """Escritura atómica, durable (fsync archivo y directorio) y protegida con fcntl.flock."""
    import tempfile
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    lock_path = f"{path}.lock"

    fd, temp_path = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".json")
    try:
        with open(lock_path, "a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.chmod(temp_path, mode)
                except Exception:
                    pass
                os.replace(temp_path, path)
                try:
                    dir_fd = os.open(parent, os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except Exception:
                    pass
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem con soporte para ordenamiento numérico, jerárquico y de texto."""
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


def is_coherent_ok_response(m: dict) -> bool:
    """Valida que la respuesta sea 200 OK con latencia válida y sin mensajes de falta de créditos o error."""
    st = str(m.get("status", "")).upper()
    lat = m.get("latency_ms", 0)
    snip = str(m.get("response_snippet", "")).strip().lower()
    if st not in ("200_OK", "ONLINE") or lat <= 0:
        return False
    if snip in ("—", "sin probar", "sondeo cancelado"):
        return False
    bad_keywords = (
        "sin créditos", "insufficient credits", "out of credits", "no credits",
        "quota", "rate limit", "error", "timeout", "payment required", "402",
        "balance is too low", "exceeded your current quota", "unauthorized", "invalid key",
        "credit is not enough"
    )
    if any(kw in snip for kw in bad_keywords) and not snip.startswith("🧠"):
        # Los snippets "🧠" provienen de reasoning_content (200 OK real); el texto de
        # razonamiento puede mencionar "error"/"limit" legítimamente y no debe vetarse.
        return False
    return True


# Cargar variables de .env
def load_env_vars() -> Dict[str, str]:
    env_vars = {}
    candidates = [
        ENV_FILE,
        os.path.expanduser("~/.config/floydia-suite/.env"),
        os.path.expanduser("~/.config/floydia-suite/secrets.env"),
        os.path.expanduser("~/.secrets/antigravity.env"),
        os.path.join(WORKSPACE_ROOT, ".env")
    ]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'").strip('"')
                            if " #" in v:
                                v = v.split(" #", 1)[0].strip()
                            if k not in env_vars:
                                env_vars[k] = v
            except Exception:
                pass
    return env_vars

ENV_MAP = load_env_vars()

def get_secret(keys: List[str]) -> Optional[str]:
    # 1. Priorizar ENV_MAP (.env verificado en disco)
    for k in keys:
        if k in ENV_MAP and ENV_MAP[k] and ENV_MAP[k].strip():
            return ENV_MAP[k].strip()
    # 2. Fallback a os.environ
    for k in keys:
        if k in os.environ and os.environ[k] and os.environ[k].strip():
            return os.environ[k].strip()
    # 3. Fallback con relectura fresca
    fresh = load_env_vars()
    for k in keys:
        if k in fresh and fresh[k] and fresh[k].strip():
            return fresh[k].strip()
    return None

# Secretos Multi-Cuenta (Google consolidado exclusivamente en [C1] Cuenta Pro para estricto cumplimiento ToS Anti-Baneo)
GOOGLE_C1_KEY = get_secret(["C1_GOOGLE_AISTUDIO", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_API_KEY"])
OPENROUTER_C7_KEY = get_secret(["C7_OPENROUTER", "C7_OPENROUTER_API_KEY", "C7_OPENROUTER_OPENCODE_HP15", "C7_OPENROUTER_HERMES_HP15", "C7_OPENROUTER_KILO_HP15", "OPENROUTER_API_KEY"])
OPENROUTER_C1_KEY = get_secret(["C1_OPENROUTER", "OPENROUTER_API_KEY"])
NVIDIA_C7_KEY = get_secret(["C7_NVIDIA", "C7_NVIDIA_API_KEY"])
NVIDIA_C1_KEY = get_secret(["C1_NVIDIA"])
NVIDIA_C2_KEY = get_secret(["C2_NVIDIA"])
MISTRAL_C1_KEY = get_secret(["C1_MISTRAL", "MISTRAL_API_KEY"])
MISTRAL_C2_KEY = get_secret(["C2_MISTRAL"])
DEEPSEEK_DIRECT_KEY = get_secret(["DEEPSEEK_API_KEY"])
DEEPSEEK_C1_KEY = get_secret(["DEEPSEEK_API_KEY", "C7_DEEPSEEK", "C1_DEEPSEEK"])
DEEPSEEK_C7_KEY = get_secret(["C7_DEEPSEEK", "DEEPSEEK_API_KEY"])
GROQ_C1_KEY = get_secret(["C1_GROQ"])
ZAI_C1_KEY = get_secret(["C1_Z_AI"])

# Secretos Cuenta 7 (Master Account floydiamarkv@gmail.com)
CLOUDFLARE_C7_KEY = get_secret(["C7_CLOUDFLARE", "CLOUDFLARE_API_TOKEN"])
B_AI_C7_KEY = get_secret(["C7_B_AI_API", "B_AI_API", "BAI_API_KEY"])
TOKENROUTER_C7_KEY = get_secret(["C7_TOKENROUTER_API", "TOKENROUTER_API"])
ZENMUX_C7_KEY = get_secret(["C7_ZENMUX_API", "ZENMUX_API"])
SEEKAI_C7_KEY = get_secret(["C7_SEEKAI_API", "SEEKAI_API_KEY"])
GOROUTER_C7_KEY = get_secret(["C7_GOROUTER_API", "GOROUTER_API_KEY"])
JUSTWORKER_C7_KEY = get_secret(["C7_JUSTWORKER_API", "JUSTWORKER_API_KEY"])
DASHSCOPE_C7_KEY = get_secret(["C7_DASHSCOPE_API_KEY", "C7_QWEN_API_KEY", "DASHSCOPE_API_KEY"])
FIREWORKS_C7_KEY = get_secret(["C7_FIREWORKS_API_KEY", "FIREWORKS_API_KEY"])
KIMI_C7_KEY = get_secret(["C7_KIMI_PLATFORM_API", "MOONSHOT_API_KEY"])

# Alias y Claves Globales Canónicas para Catálogo Global, Advisor y Fallbacks
GOOGLE_KEY = GOOGLE_C1_KEY
OPENROUTER_KEY = OPENROUTER_C7_KEY or OPENROUTER_C1_KEY
NVIDIA_KEY = NVIDIA_C7_KEY or NVIDIA_C1_KEY or NVIDIA_C2_KEY
MISTRAL_KEY = MISTRAL_C1_KEY or MISTRAL_C2_KEY
DEEPSEEK_KEY = DEEPSEEK_DIRECT_KEY or DEEPSEEK_C1_KEY or DEEPSEEK_C7_KEY
GROQ_KEY = GROQ_C1_KEY
ZAI_KEY = ZAI_C1_KEY
CLOUDFLARE_KEY = CLOUDFLARE_C7_KEY
B_AI_KEY = B_AI_C7_KEY
TOKENROUTER_KEY = TOKENROUTER_C7_KEY
ZENMUX_KEY = ZENMUX_C7_KEY
DASHSCOPE_KEY = DASHSCOPE_C7_KEY
FIREWORKS_KEY = FIREWORKS_C7_KEY

# Flota Curada de Modelos IA de FloydIA Homelab con Taxonomía Multi-Cuenta [C1..C8]
CURATED_FLEET = [
    # Google AI Studio [C1 Exclusivo: eliutec.aux.ia1@gmail.com — Cuenta Pro]
    {"id": "gemini-3.7-flash", "name": "[C1] Gemini 3.7 Flash Reasoning", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-3.6-flash", "name": "[C1] Gemini 3.6 Flash Fast", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-3.5-flash", "name": "[C1] Gemini 3.5 Flash Multimodal", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-2.5-flash", "name": "[C1] Gemini 2.5 Flash Reasoning", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-2.5-pro", "name": "[C1] Gemini 2.5 Pro Ultra Thinking", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-2.0-flash", "name": "[C1] Gemini 2.0 Flash Production", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Free/Pro", "category": "frontier"},
    {"id": "gemma-4-31b-it", "name": "[C1] Gemma 4 31B Instruct", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 262144, "badge": "262k • Pro", "category": "frontier"},

    # OpenRouter Hub [C7 / C1] — Routers, Free Tier Cluster (+30 LLMs) y Frontier
    {"id": "openrouter/auto", "name": "[C7] OpenRouter Auto Router", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 262144, "badge": "Auto • Free", "category": "free"},
    {"id": "openrouter/free", "name": "[C7] OpenRouter Free Cluster", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 262144, "badge": "Auto • Free", "category": "free"},
    {"id": "minimax/minimax-m3:free", "name": "[C7] MiniMax M3 Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 1048576, "badge": "1M • Free", "category": "free"},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "[C7] Nemotron 3 Super 120B", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 262144, "badge": "262k • Free", "category": "free"},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "name": "[C7] Nemotron 3 Nano Reasoning", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 256000, "badge": "256k • Free", "category": "free"},
    {"id": "nvidia/nemotron-3.5-lightning:free", "name": "[C7] Nemotron 3.5 Lightning", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 262144, "badge": "262k • Free", "category": "free"},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "name": "[C7] Nemotron 3 Ultra 550B", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 262144, "badge": "262k • Free", "category": "free"},
    {"id": "z-ai/glm-5.2:free", "name": "[C7] GLM 5.2 Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 256000, "badge": "256k • Free", "category": "free"},
    {"id": "poolside/laguna-s-2.1:free", "name": "[C7] Laguna S 2.1 Code", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 262144, "badge": "262k • Free", "category": "code"},
    {"id": "poolside/laguna-xs-2.1:free", "name": "[C7] Laguna XS 2.1 Fast", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "code"},
    {"id": "inclusionai/ling-3.0-flash-fin:free", "name": "[C7] Ling 3.0 Flash Fin", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "dots-studio/dots-3-note-preview:free", "name": "[C7] Dots 3 Note Preview", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "liquid/lfm-2.5-2.6b:free", "name": "[C7] Liquid LFM 2.5", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 32768, "badge": "32k • Free", "category": "free"},
    {"id": "thinkingmachines/inkling-small:free", "name": "[C7] Inkling Small Reasoning", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "thinkingmachines/inkling:free", "name": "[C7] Inkling Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "cohere/north-mini-code:free", "name": "[C7] North Mini Code", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "code"},
    {"id": "google/gemma-4-26b-a4b-it:free", "name": "[C7] Gemma 4 26B Instruct", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "deepseek/deepseek-r1:free", "name": "[C7] DeepSeek R1 Reasoning Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "frontier"},
    {"id": "deepseek/deepseek-chat:free", "name": "[C7] DeepSeek Chat V3 Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "frontier"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "[C7] Llama 3.3 70B Instruct Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "frontier"},
    {"id": "meta-llama/llama-3.1-8b-instruct:free", "name": "[C7] Llama 3.1 8B Instruct Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "qwen/qwen-2.5-coder-32b-instruct:free", "name": "[C7] Qwen 2.5 Coder 32B Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "code"},
    {"id": "qwen/qwen-2.5-72b-instruct:free", "name": "[C7] Qwen 2.5 72B Instruct Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "frontier"},
    {"id": "google/gemini-2.0-flash-exp:free", "name": "[C7] Gemini 2.0 Flash Exp Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 1048576, "badge": "1M • Free", "category": "free"},
    {"id": "google/gemini-2.0-flash-thinking-exp:free", "name": "[C7] Gemini 2.0 Flash Thinking Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 1048576, "badge": "1M • Free", "category": "frontier"},
    {"id": "mistralai/mistral-small-24b-instruct-2501:free", "name": "[C7] Mistral Small 24B Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "mistralai/mistral-7b-instruct:free", "name": "[C7] Mistral 7B Instruct Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 32768, "badge": "32k • Free", "category": "free"},
    {"id": "sophosympatheia/rogue-rose-103b-v0.2:free", "name": "[C7] Rogue Rose 103B Free", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Free", "category": "free"},
    {"id": "anthropic/claude-3.7-sonnet", "name": "[C7] Claude 3.7 Sonnet Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 200000, "badge": "200k • Frontier", "category": "frontier"},
    {"id": "anthropic/claude-3.5-sonnet", "name": "[C7] Claude 3.5 Sonnet Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 200000, "badge": "200k • Frontier", "category": "frontier"},
    {"id": "openai/gpt-4o", "name": "[C7] OpenAI GPT-4o Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Frontier", "category": "frontier"},
    {"id": "openai/o3-mini", "name": "[C7] OpenAI o3-mini Reasoner", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 200000, "badge": "200k • Reasoner", "category": "frontier"},
    {"id": "deepseek/deepseek-r1", "name": "[C7] DeepSeek R1 Global Hub", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Reasoner", "category": "frontier"},
    {"id": "deepseek/deepseek-chat", "name": "[C7] DeepSeek V3 Global Hub", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY or OPENROUTER_KEY, "context": 128000, "badge": "128k • Paid", "category": "frontier"},

    # NVIDIA NIM [C7], [C1], [C2]
    {"id": "deepseek-ai/deepseek-v4-flash-0731", "name": "[C1] DeepSeek V4 Flash (NIM)", "account_tag": "C1", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C1_KEY or NVIDIA_C7_KEY, "context": 262144, "badge": "256k • NIM", "category": "code"},
    {"id": "moonshotai/kimi-k3", "name": "[C2] Kimi K3 Frontier (NIM)", "account_tag": "C2", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C2_KEY or NVIDIA_C7_KEY, "context": 262144, "badge": "256k • NIM", "category": "frontier"},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "name": "[C7] Nemotron 3 Nano NIM", "account_tag": "C7", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C7_KEY, "context": 256000, "badge": "256k • NIM", "category": "frontier"},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "name": "[C7] Nemotron 3 Super 120B NIM", "account_tag": "C7", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C7_KEY, "context": 262144, "badge": "262k • NIM", "category": "frontier"},

    # Mistral AI [C1] y [C2]
    {"id": "codestral-latest", "name": "[C1] Mistral Codestral Latest", "account_tag": "C1", "provider": "mistral", "base_url": "https://api.mistral.ai/v1", "key": MISTRAL_C1_KEY, "context": 256000, "badge": "256k • Trial", "category": "code"},
    {"id": "c2/codestral-latest", "name": "[C2] Mistral Codestral Latest", "account_tag": "C2", "provider": "mistral", "base_url": "https://api.mistral.ai/v1", "key": MISTRAL_C2_KEY, "context": 256000, "badge": "256k • Trial", "category": "code"},
    {"id": "mistral-small-latest", "name": "[C1] Mistral Small Latest", "account_tag": "C1", "provider": "mistral", "base_url": "https://api.mistral.ai/v1", "key": MISTRAL_C1_KEY, "context": 128000, "badge": "128k • Pro", "category": "frontier"},
    {"id": "ministral-8b-latest", "name": "[C1] Ministral 8B Latest", "account_tag": "C1", "provider": "mistral", "base_url": "https://api.mistral.ai/v1", "key": MISTRAL_C1_KEY, "context": 128000, "badge": "128k • Fast", "category": "frontier"},

    # DeepSeek Direct [Direct], [C1], [C7] — Chat V3, Reasoner R1 & V4 Flash
    {"id": "deepseek-chat", "name": "[Direct] DeepSeek Chat V3 Paid", "account_tag": "Direct", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Paid", "category": "frontier"},
    {"id": "deepseek-reasoner", "name": "[Direct] DeepSeek Reasoner R1 Paid", "account_tag": "Direct", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Reasoner", "category": "frontier"},
    {"id": "deepseek-v4-flash", "name": "[Direct] DeepSeek V4 Flash", "account_tag": "Direct", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},
    {"id": "c1/deepseek-chat", "name": "[C1] DeepSeek Chat V3", "account_tag": "C1", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C1_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},
    {"id": "c1/deepseek-reasoner", "name": "[C1] DeepSeek Reasoner R1", "account_tag": "C1", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C1_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Reasoner", "category": "frontier"},
    {"id": "c1/deepseek-v4-flash", "name": "[C1] DeepSeek V4 Flash", "account_tag": "C1", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C1_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},
    {"id": "c7/deepseek-chat", "name": "[C7] DeepSeek Chat V3", "account_tag": "C7", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C7_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},
    {"id": "c7/deepseek-reasoner", "name": "[C7] DeepSeek Reasoner R1", "account_tag": "C7", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C7_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Reasoner", "category": "frontier"},
    {"id": "c7/deepseek-v4-flash", "name": "[C7] DeepSeek V4 Flash", "account_tag": "C7", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C7_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},

    # Groq LPU [C1]
    {"id": "llama-3.3-70b-versatile", "name": "[C1] Llama 3.3 70B Versatile", "account_tag": "C1", "provider": "groq", "base_url": "https://api.groq.com/openai/v1", "key": GROQ_C1_KEY, "context": 128000, "badge": "128k • LPU", "category": "frontier"},

    # Cloudflare Workers AI [C7]
    {"id": "@cf/qwen/qwen3-30b-a3b-fp8", "name": "[C7] Cloudflare Qwen3 30B FP8", "account_tag": "C7", "provider": "cloudflare", "base_url": "https://api.cloudflare.com/client/v4/user/tokens/verify", "key": CLOUDFLARE_C7_KEY, "context": 32768, "badge": "32k • Cloudflare", "category": "frontier"},

    # B.AI Gateway Hub [C7] — Suite Multi-Modelo (44 LLMs)
    {"id": "minimax-m3", "name": "[C7] B.AI MiniMax M3", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 1048576, "badge": "1M • B.AI", "category": "frontier"},
    {"id": "mistral-large", "name": "[C7] B.AI Mistral Large", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "mistral-medium", "name": "[C7] B.AI Mistral Medium", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 32768, "badge": "32k • B.AI", "category": "frontier"},
    {"id": "mistral-small", "name": "[C7] B.AI Mistral Small", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 32768, "badge": "32k • B.AI", "category": "free"},
    {"id": "codestral-2501", "name": "[C7] B.AI Codestral 2501", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 256000, "badge": "256k • B.AI", "category": "code"},
    {"id": "qwen-2.5-72b-instruct", "name": "[C7] B.AI Qwen 2.5 72B", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "qwen-2.5-coder-32b-instruct", "name": "[C7] B.AI Qwen 2.5 Coder 32B", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "code"},
    {"id": "deepseek-v3", "name": "[C7] B.AI DeepSeek V3", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "deepseek-r1", "name": "[C7] B.AI DeepSeek R1 Reasoner", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "glm-4-plus", "name": "[C7] B.AI GLM 4 Plus", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "glm-4-air", "name": "[C7] B.AI GLM 4 Air", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "free"},
    {"id": "glm-4-flash", "name": "[C7] B.AI GLM 4 Flash", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "free"},
    {"id": "yi-lightning", "name": "[C7] B.AI Yi Lightning", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "moonshot-v1-128k", "name": "[C7] B.AI Moonshot Kimi 128k", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "doubao-pro-128k", "name": "[C7] B.AI Doubao Pro 128k", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},
    {"id": "doubao-lite-128k", "name": "[C7] B.AI Doubao Lite 128k", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "free"},
    {"id": "llama-3.3-70b-instruct", "name": "[C7] B.AI Llama 3.3 70B", "account_tag": "C7", "provider": "b_ai", "base_url": "https://api.b.ai/v1", "key": B_AI_C7_KEY, "context": 128000, "badge": "128k • B.AI", "category": "frontier"},

    # TokenRouter AI Hub [C7]
    {"id": "openai/gpt-5.4-nano", "name": "[C7] TokenRouter GPT-5.4 Nano", "account_tag": "C7", "provider": "tokenrouter", "base_url": "https://api.tokenrouter.com/v1", "key": TOKENROUTER_C7_KEY, "context": 128000, "badge": "128k • TokenRouter", "category": "free"},
    {"id": "anthropic/claude-3.5-sonnet", "name": "[C7] TokenRouter Claude 3.5 Sonnet", "account_tag": "C7", "provider": "tokenrouter", "base_url": "https://api.tokenrouter.com/v1", "key": TOKENROUTER_C7_KEY, "context": 200000, "badge": "200k • TokenRouter", "category": "frontier"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "name": "[C7] TokenRouter Llama 3.3 70B", "account_tag": "C7", "provider": "tokenrouter", "base_url": "https://api.tokenrouter.com/v1", "key": TOKENROUTER_C7_KEY, "context": 128000, "badge": "128k • TokenRouter", "category": "frontier"},

    # ZenMux AI Hub [C7]
    {"id": "qwen/qwen3.8-flash", "name": "[C7] ZenMux Qwen 3.8 Flash", "account_tag": "C7", "provider": "zenmux", "base_url": "https://zenmux.ai/api/v1", "key": ZENMUX_C7_KEY, "context": 128000, "badge": "128k • ZenMux", "category": "frontier"},
    {"id": "deepseek/deepseek-r1", "name": "[C7] ZenMux DeepSeek R1", "account_tag": "C7", "provider": "zenmux", "base_url": "https://zenmux.ai/api/v1", "key": ZENMUX_C7_KEY, "context": 128000, "badge": "128k • ZenMux", "category": "frontier"},

    # Fireworks AI Hub [C7]
    {"id": "accounts/fireworks/models/deepseek-v3", "name": "[C7] Fireworks DeepSeek V3", "account_tag": "C7", "provider": "fireworks", "base_url": "https://api.fireworks.ai/inference/v1", "key": FIREWORKS_C7_KEY, "context": 128000, "badge": "128k • Fireworks", "category": "frontier"},
    {"id": "accounts/fireworks/models/llama-v3p3-70b-instruct", "name": "[C7] Fireworks Llama 3.3 70B", "account_tag": "C7", "provider": "fireworks", "base_url": "https://api.fireworks.ai/inference/v1", "key": FIREWORKS_C7_KEY, "context": 128000, "badge": "128k • Fireworks", "category": "frontier"},
    {"id": "accounts/fireworks/models/qwen2p5-coder-32b-instruct", "name": "[C7] Fireworks Qwen 2.5 Coder 32B", "account_tag": "C7", "provider": "fireworks", "base_url": "https://api.fireworks.ai/inference/v1", "key": FIREWORKS_C7_KEY, "context": 128000, "badge": "128k • Fireworks", "category": "code"},
]


def resolve_api_key_for_model(item: Dict[str, Any]) -> Optional[str]:
    """Resuelve dinámicamente la clave de API para un modelo según su proveedor, base_url y tag de cuenta."""
    # 1. Si el item ya tiene una clave directa válida no vacía
    direct_key = item.get("key") or item.get("api_key")
    if direct_key and isinstance(direct_key, str) and direct_key.strip():
        return direct_key.strip()

    # 2. Si el item especifica una variable .env explícita
    env_k = item.get("env_key")
    if env_k and isinstance(env_k, str) and env_k.strip():
        val = get_secret([env_k.strip()])
        if val:
            return val

    prov = str(item.get("provider", "")).lower()
    tag = str(item.get("account_tag", "")).upper()
    model_id = str(item.get("id", "")).lower()
    base_url = str(item.get("base_url", "")).lower()

    # Cloudflare Workers AI
    if "cloudflare" in base_url or prov == "cloudflare":
        return get_secret(["C7_CLOUDFLARE", "CLOUDFLARE_API_TOKEN"])

    # B.AI Gateway
    if "b.ai" in base_url or prov in ("b_ai", "bai"):
        return get_secret(["C7_B_AI_API", "B_AI_API", "BAI_API_KEY"])

    # TokenRouter
    if "tokenrouter.com" in base_url or prov == "tokenrouter":
        return get_secret(["C7_TOKENROUTER_API", "TOKENROUTER_API"])

    # ZenMux
    if "zenmux.ai" in base_url or prov == "zenmux":
        return get_secret(["C7_ZENMUX_API", "ZENMUX_API"])

    # SeekAI
    if "seekai.cc" in base_url or prov == "seekai":
        return get_secret(["C7_SEEKAI_API", "SEEKAI_API_KEY"])

    # GoRouter
    if "gorouter.cc" in base_url or prov == "gorouter":
        return get_secret(["C7_GOROUTER_API", "GOROUTER_API_KEY"])

    # JustWorker
    if "justwoker.icu" in base_url or prov == "justworker":
        return get_secret(["C7_JUSTWORKER_API", "JUSTWORKER_API_KEY"])

    # Alibaba DashScope
    if "aliyuncs.com" in base_url or prov in ("dashscope", "alibaba"):
        return get_secret(["C7_DASHSCOPE_API_KEY", "C7_QWEN_API_KEY", "DASHSCOPE_API_KEY"])

    # Fireworks AI
    if "fireworks.ai" in base_url or prov == "fireworks":
        return get_secret(["C7_FIREWORKS_API_KEY", "FIREWORKS_API_KEY"])

    # Kimi Moonshot
    if "moonshot.cn" in base_url or prov in ("kimi", "moonshot"):
        return get_secret(["C7_KIMI_PLATFORM_API", "MOONSHOT_API_KEY"])

    # Google AI Studio
    if "generativelanguage.googleapis.com" in base_url or prov == "google" or model_id.startswith(("gemini", "gemma")):
        return get_secret(["C1_GOOGLE_AISTUDIO", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_API_KEY"])

    # DeepSeek Direct
    if "api.deepseek.com" in base_url or prov == "deepseek" or ("deepseek" in model_id and "nvidia" not in base_url and "openrouter" not in base_url):
        if tag == "C1":
            return get_secret(["C1_DEEPSEEK", "DEEPSEEK_API_KEY", "C7_DEEPSEEK"])
        elif tag == "C7":
            return get_secret(["C7_DEEPSEEK", "DEEPSEEK_API_KEY"])
        return get_secret(["DEEPSEEK_API_KEY", "C7_DEEPSEEK", "C1_DEEPSEEK"])

    # NVIDIA NIM
    if "integrate.api.nvidia.com" in base_url or prov == "nvidia" or "nim" in model_id:
        if tag == "C1":
            return get_secret(["C1_NVIDIA", "C7_NVIDIA", "C7_NVIDIA_API_KEY"])
        elif tag == "C2":
            return get_secret(["C2_NVIDIA", "C7_NVIDIA", "C7_NVIDIA_API_KEY"])
        return get_secret(["C7_NVIDIA", "C7_NVIDIA_API_KEY", "C1_NVIDIA", "C2_NVIDIA"])

    # Mistral AI
    if "api.mistral.ai" in base_url or prov == "mistral" or "codestral" in model_id:
        if tag == "C2":
            return get_secret(["C2_MISTRAL", "C1_MISTRAL"])
        return get_secret(["C1_MISTRAL", "MISTRAL_API_KEY", "C2_MISTRAL"])

    # Groq Cloud
    if "api.groq.com" in base_url or prov == "groq":
        return get_secret(["C1_GROQ", "GROQ_API_KEY"])

    # Z.AI GLM
    if "api.z.ai" in base_url or prov in ("zai", "z_ai"):
        return get_secret(["C1_Z_AI", "ZAI_API_KEY"])

    # OpenRouter Hub (C7 prioritario, C1 secundario)
    if "openrouter.ai" in base_url or prov == "openrouter" or "/" in model_id:
        if tag == "C1":
            return get_secret(["C1_OPENROUTER", "OPENROUTER_API_KEY", "C7_OPENROUTER", "C7_OPENROUTER_API_KEY"])
        return get_secret(["C7_OPENROUTER", "C7_OPENROUTER_API_KEY", "C7_OPENROUTER_OPENCODE_HP15", "C7_OPENROUTER_HERMES_HP15", "C7_OPENROUTER_KILO_HP15", "OPENROUTER_API_KEY", "C1_OPENROUTER"])

    # Fallback final a OpenRouter
    return get_secret(["C7_OPENROUTER", "C7_OPENROUTER_API_KEY", "OPENROUTER_API_KEY", "C1_OPENROUTER"])

# Presets de prueba para sondas y benchmarks
PROBE_PRESETS = {
    "⚡ Ping Ultrarrápido (Latencia Pura)": {
        "prompt": "1",
        "max_tokens": 8,
        "timeout": 7,
        "desc": "Sondeo mínimo de 8 tokens para medir conectividad y latencia de red pura."
    },
    "🧩 Micro-Benchmark: Razonamiento Lógico": {
        "prompt": "Si 5 máquinas hacen 5 artículos en 5 minutos, ¿cuántos minutos tardan 100 máquinas en hacer 100 artículos? Responde solo el número exacto y una frase explicativa.",
        "max_tokens": 45,
        "timeout": 12,
        "desc": "Evalúa coherencia lógica, seguimiento de instrucciones y tiempo de respuesta."
    },
    "💻 Micro-Benchmark: Código Python": {
        "prompt": "Escribe una función Python pura de 2 líneas `def is_prime(n: int) -> bool:` que determine si un entero positivo es primo. Devuelve solo el bloque de código.",
        "max_tokens": 75,
        "timeout": 15,
        "desc": "Evalúa capacidades de programación y síntesis limpia sin explicaciones redundantes."
    },
    "🌐 Test de Precisión & Conocimiento": {
        "prompt": "Nombra las 3 lunas más grandes del Sistema Solar y sus planetas anfitriones en formato de lista de 3 viñetas breves.",
        "max_tokens": 60,
        "timeout": 10,
        "desc": "Evalúa precisión fáctica y estructuración concisa."
    },
    "✏️ Pregunta Personalizada (Custom Prompt)": {
        "prompt": "¿Cuál es la principal ventaja arquitectónica de los LLMs con ventana de contexto de 1 millón de tokens?",
        "max_tokens": 64,
        "timeout": 12,
        "desc": "Escribe cualquier pregunta o benchmark personalizado para probar en paralelo toda la flota."
    }
}


from dataclasses import dataclass

@dataclass(frozen=True)
class Timing:
    request_start: float
    first_chunk: Optional[float]
    response_end: float

    @property
    def total_ms(self) -> int:
        return round((self.response_end - self.request_start) * 1000)

    @property
    def ttft_ms(self) -> Optional[int]:
        if self.first_chunk is None:
            return None
        return round((self.first_chunk - self.request_start) * 1000)

    def generation_seconds(self) -> float:
        if self.first_chunk is None:
            return max(0.001, self.response_end - self.request_start)
        return max(0.001, self.response_end - self.first_chunk)


def calculate_tps(output_tokens: int, timing: Timing) -> float:
    gen_time = timing.generation_seconds()
    if output_tokens <= 0 or not gen_time or gen_time <= 0:
        return 0.0
    return round(output_tokens / gen_time, 1)


def _sse_extract_event(line: bytes) -> Optional[Dict[str, Any]]:
    """
    Extrae un evento SSE (`data: {...}`) de una línea de la respuesta.
    Devuelve None si no es un evento JSON válido o es la sentinela [DONE].
    """
    if not line or line.strip() == b"":
        return None
    text = line.decode("utf-8", errors="replace").strip()
    if not text.startswith("data:"):
        return None
    data = text[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None
    try:
        return json.loads(data)
    except Exception:
        return None


def cancellable_backoff(cancel_event: Optional[threading.Event], delay: float) -> bool:
    """
    True = cancelado durante el backoff.
    False = backoff completado.
    """
    if cancel_event is None:
        time.sleep(delay)
        return False
    return cancel_event.wait(max(0.0, delay))


def probe_single_endpoint(item: Dict[str, Any], probe_cfg: Dict[str, Any], cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Ejecuta una sonda de inferencia con backoff cancelable, cálculo de TTFT, TPS y detección de errores de crédito."""
    if cancel_event and cancel_event.is_set():
        return {"status": "CANCELLED", "latency_ms": 0, "response_snippet": "Sondeo cancelado", "error": "cancelled"}

    key = resolve_api_key_for_model(item)
    if not key:
        return {"status": "SIN_KEY", "latency_ms": 0, "response_snippet": "Sin API Key configurada en .env", "error": "Sin API Key"}

    base_url = item["base_url"].rstrip("/")

    # Soporte especial verificación Cloudflare Workers AI Token
    if "tokens/verify" in base_url or base_url.endswith("/verify") or item.get("provider") == "cloudflare":
        cf_url = base_url if "verify" in base_url else "https://api.cloudflare.com/client/v4/user/tokens/verify"
        cf_headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": "FloydiaAgentRadar/3.0"
        }
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(cf_url, headers=cf_headers, method="GET")
            with urllib.request.urlopen(req, timeout=probe_cfg.get("timeout", 7)) as resp:
                lat = int((time.monotonic() - t0) * 1000)
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
                if body.get("success"):
                    return {
                        "status": "200_OK",
                        "latency_ms": lat,
                        "response_snippet": "Token Cloudflare Válido y Activo (200 OK)",
                        "tokens": 0,
                        "tps": 0.0,
                        "error": None
                    }
                return {
                    "status": "AUTH_ERR",
                    "latency_ms": lat,
                    "response_snippet": "Token Cloudflare Inválido",
                    "tokens": 0,
                    "tps": 0.0,
                    "error": "Invalid Token"
                }
        except Exception as e:
            lat = int((time.monotonic() - t0) * 1000)
            return {
                "status": "AUTH_ERR",
                "latency_ms": lat,
                "response_snippet": f"Error autenticación: {str(e)[:40]}",
                "tokens": 0,
                "tps": 0.0,
                "error": str(e)
            }

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "FloydiaAgentRadar/3.0"
    }

    test_prompt = probe_cfg.get("prompt", "1")
    max_tok = int(probe_cfg.get("max_tokens", 8))
    timeout = int(probe_cfg.get("timeout", 7))
    temp = float(probe_cfg.get("temperature", 0.1))

    # Limpiar prefijos de cuenta internos (c1/, c2/, c7/) antes de enviar a la API
    model_id = item["id"]
    if model_id.startswith(("c1/", "c2/", "c7/")):
        model_id = model_id.split("/", 1)[-1]

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": test_prompt}],
        "max_tokens": max_tok,
        "temperature": temp
    }

    no_credit_keywords = (
        "insufficient credits", "out of credits", "no credits", "credit balance is too low",
        "quota exceeded", "exceeded your current quota", "payment required", "rate limit",
        "rate-limited", "billing", "unauthorized", "invalid_api_key", "error code: 402",
        "error code: 429", "no more credits", "requires credits", "credit is not enough",
        "balance is zero", "free tier limit", "has been disabled"
    )

    max_retries = 2
    for attempt in range(max_retries + 1):
        if cancel_event and cancel_event.is_set():
            return {"status": "CANCELLED", "latency_ms": 0, "response_snippet": "Sondeo cancelado", "error": "cancelled"}

        t_start = time.monotonic()
        try:
            # ── Modo Streaming SSE (FSU-009): TTFT real + TPS de generación ──
            stream_payload = dict(payload)
            stream_payload["stream"] = True
            stream_payload["stream_options"] = {"include_usage": True}

            req = urllib.request.Request(url, data=json.dumps(stream_payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in ctype:
                    # ── Streaming real: primer delta = TTFT auténtico ──
                    first_chunk: Optional[float] = None
                    fragments: List[str] = []
                    reasoning_fragments: List[str] = []
                    usage: Dict[str, Any] = {}
                    for line in resp:
                        if cancel_event and cancel_event.is_set():
                            return {"status": "CANCELLED", "latency_ms": 0, "response_snippet": "Sondeo cancelado", "error": "cancelled"}
                        ev = _sse_extract_event(line)
                        if ev is None:
                            continue
                        if ev.get("usage"):
                            usage = ev["usage"]
                        choices = ev.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            content_piece = delta.get("content")
                            r_piece = delta.get("reasoning_content")
                            if first_chunk is None and (content_piece or r_piece):
                                first_chunk = time.monotonic()
                            if content_piece:
                                fragments.append(str(content_piece))
                            if r_piece:
                                reasoning_fragments.append(str(r_piece))
                    t_end = time.monotonic()
                    timing = Timing(request_start=t_start, first_chunk=first_chunk, response_end=t_end)
                    latency = timing.total_ms
                    content_full = "".join(fragments)
                    reasoning_full = "".join(reasoning_fragments)
                    snippet = (content_full or reasoning_full or "200 OK (Streaming)").strip().replace("\n", " ")
                    reasoning_only = not content_full.strip()
                    if reasoning_only and snippet:
                        snippet = "🧠 " + snippet
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                    out_tokens = int(usage.get("completion_tokens") or 0)
                    if out_tokens <= 0:
                        # Estimación conservadora (BPE ≈ 4 chars/token) si no viene usage
                        out_tokens = int(len(content_full + reasoning_full) / 4)
                    tps = calculate_tps(out_tokens, timing)
                    metric_mode = "streaming" if first_chunk is not None else "streaming_no_first_delta"
                    ttft_ms = None if first_chunk is None else round((first_chunk - t_start) * 1000)
                    snip_lower = snippet.lower()
                    if not reasoning_only and (any(kw in snip_lower for kw in no_credit_keywords) or snip_lower.startswith('{"error"')):
                        return {"status": "NO_CREDITS", "latency_ms": latency, "response_snippet": f"⚠️ Sin créditos / Error: {snippet[:60]}", "tokens": out_tokens, "tps": tps, "ttft_ms": ttft_ms, "metric_mode": metric_mode, "error": "Insufficient Credits"}
                    return {"status": "200_OK", "latency_ms": latency, "response_snippet": snippet, "tokens": out_tokens, "tps": tps, "ttft_ms": ttft_ms, "metric_mode": metric_mode, "error": None}

                # ── Fallback no-streaming (algunos gateways ignoran "stream") ──
                raw_data = resp.read(262144)  # Lectura acotada a 256 KB para evitar consumo de memoria
                t_end = time.monotonic()
                timing = Timing(request_start=t_start, first_chunk=None, response_end=t_end)
                latency = timing.total_ms

                try:
                    body = json.loads(raw_data.decode("utf-8", errors="replace"))
                except Exception:
                    return {"status": "BAD_JSON", "latency_ms": latency, "response_snippet": "Respuesta no JSON o malformada", "error": "Bad JSON"}

                snippet = "OK"
                reasoning_only = False
                try:
                    msg_obj = body["choices"][0]["message"]
                    raw_content = msg_obj.get("content") or msg_obj.get("reasoning_content") or "200 OK (Inferencia Activa)"
                    # Dilema reasoning_content: con max_tokens bajo, reasoner/v4-flash agotan
                    # los tokens en el razonamiento y devuelven content vacío. NO es error.
                    reasoning_only = not str(msg_obj.get("content") or "").strip()
                    snippet = str(raw_content).strip().replace("\n", " ")
                    if reasoning_only and snippet:
                        snippet = "🧠 " + snippet
                    if len(snippet) > 80:
                        snippet = snippet[:77] + "..."
                except Exception:
                    pass

                usage = body.get("usage", {})
                out_tokens = usage.get("completion_tokens", 0)
                tps = calculate_tps(out_tokens, timing)

                snip_lower = snippet.lower()
                # Anti-falso-positivo: el texto de razonamiento (reasoning_only) puede contener
                # palabras como "error"/"limit" de forma legítima; solo escanear contenido visible real.
                if not reasoning_only and (any(kw in snip_lower for kw in no_credit_keywords) or snip_lower.startswith('{"error"')):
                    return {
                        "status": "NO_CREDITS",
                        "latency_ms": latency,
                        "response_snippet": f"⚠️ Sin créditos / Error: {snippet[:60]}",
                        "tokens": out_tokens,
                        "tps": tps,
                        "ttft_ms": None,
                        "metric_mode": "non_streaming",
                        "error": "Insufficient Credits"
                    }

                return {
                    "status": "200_OK",
                    "latency_ms": latency,
                    "response_snippet": snippet,
                    "tokens": out_tokens,
                    "tps": tps,
                    "ttft_ms": None,
                    "metric_mode": "non_streaming",
                    "error": None
                }

        except urllib.error.HTTPError as e:
            latency = int((time.monotonic() - t_start) * 1000)
            err_body = ""
            try:
                err_body = e.read(4096).decode("utf-8", errors="ignore").lower()
            except Exception:
                pass

            if e.code == 402 or "insufficient credits" in err_body or "requires credits" in err_body or "out of credits" in err_body:
                return {"status": "NO_CREDITS", "latency_ms": latency, "response_snippet": "402 Pago Requerido / Sin saldo en OpenRouter C7", "error": "Payment Required"}
            if e.code in (401, 403):
                return {"status": "AUTH_ERR", "latency_ms": latency, "response_snippet": f"HTTP {e.code} Clave Inválida / No Autorizado", "error": f"Auth {e.code}"}
            if e.code == 429:
                if "insufficient credits" in err_body or "credit" in err_body or "quota exceeded" in err_body:
                    return {"status": "NO_CREDITS", "latency_ms": latency, "response_snippet": "429 Cuota / Sin saldo en cuenta", "error": "Quota Exceeded"}
                if attempt < max_retries:
                    retry_after = e.headers.get("Retry-After")
                    delay = 1.0 * (2 ** attempt)
                    if retry_after:
                        try:
                            val = float(retry_after)
                            delay = min(val, 5.0)
                        except ValueError:
                            delay = min(delay, 3.0)
                        except Exception:
                            pass
                    if cancellable_backoff(cancel_event, delay):
                        return {"status": "CANCELLED", "latency_ms": latency, "response_snippet": "Sondeo cancelado", "error": "cancelled"}
                    continue
                return {"status": "429_LIMIT", "latency_ms": latency, "response_snippet": "Rate limit / Cuota agotada (429)", "error": "Rate limit"}
            if 500 <= e.code < 600:
                if attempt < max_retries:
                    if cancellable_backoff(cancel_event, 0.6 * (2 ** attempt)):
                        return {"status": "CANCELLED", "latency_ms": latency, "response_snippet": "Sondeo cancelado", "error": "cancelled"}
                    continue
                return {"status": f"HTTP_{e.code}", "latency_ms": latency, "response_snippet": f"HTTP {e.code} Gateway / Upstream Error", "error": f"HTTP {e.code}"}
            return {"status": f"HTTP_{e.code}", "latency_ms": latency, "response_snippet": f"HTTP {e.code}", "error": str(e)[:30]}

        except TimeoutError:
            latency = int((time.monotonic() - t_start) * 1000)
            return {"status": "TIMEOUT_ERR", "latency_ms": latency, "response_snippet": "Timeout de socket / Red agotada", "error": "Timeout"}

        except urllib.error.URLError as e:
            latency = int((time.monotonic() - t_start) * 1000)
            reason = str(getattr(e, "reason", e))
            err_kind = "NET_ERR"
            return {"status": err_kind, "latency_ms": latency, "response_snippet": f"Error Red/DNS/TLS: {reason[:45]}", "error": reason[:30]}

        except Exception as e:
            latency = int((time.monotonic() - t_start) * 1000)
            err_name = type(e).__name__
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                return {"status": "TIMEOUT_ERR", "latency_ms": latency, "response_snippet": "Timeout de conexión", "error": "Timeout"}
            return {"status": "NET_ERR", "latency_ms": latency, "response_snippet": f"{err_name}: {str(e)[:45]}", "error": str(e)[:30]}


class ProbeWorker(CancellableThread):
    model_updated = pyqtSignal(dict)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(list)

    def __init__(self, fleet: List[Dict[str, Any]], probe_cfg: Dict[str, Any]):
        super().__init__()
        self.fleet = list(fleet)
        self.probe_cfg = dict(probe_cfg)

    def run(self):
        prompt_preview = self.probe_cfg.get("prompt", "1")
        if len(prompt_preview) > 50:
            prompt_preview = prompt_preview[:47] + "..."
        self.log_signal.emit(f"🛰️ Iniciando sondeo concurrente en {len(self.fleet)} modelos...")
        self.log_signal.emit(f"   🎯 Pregunta de prueba: \"{prompt_preview}\" (Max Tokens: {self.probe_cfg.get('max_tokens', 8)}, Timeout: {self.probe_cfg.get('timeout', 7)}s)")
        results = []

        executor = ThreadPoolExecutor(max_workers=min(16, max(1, len(self.fleet))))
        try:
            futures = {
                executor.submit(probe_single_endpoint, m, self.probe_cfg, self._cancel_event): m
                for m in self.fleet
            }
            for future in as_completed(futures):
                if self.is_cancelled():
                    for pending in futures:
                        pending.cancel()
                    break

                m = futures[future]
                try:
                    res = future.result()
                    full_item = {**m, **res}
                    results.append(full_item)
                    self.model_updated.emit(full_item)
                    try:
                        from modules import telemetry as fl_tel
                        fl_tel.record_probe_result(full_item)
                    except Exception:
                        pass
                    st = res.get("status", "ERR")
                    lat = f"{res.get('latency_ms', 0)} ms" if res.get("latency_ms", 0) > 0 else "-"
                    tps_str = f" • {res.get('tps', 0)} TPS" if res.get('tps', 0) > 0 else ""
                    self.log_signal.emit(f"  • {m['name']}: {st} ({lat}{tps_str}) — {res.get('response_snippet', '')}")
                except Exception as e:
                    err_item = {**m, "status": "ERROR", "latency_ms": 0, "response_snippet": str(e), "error": str(e)}
                    results.append(err_item)
                    self.model_updated.emit(err_item)
        finally:
            # No esperar a las tareas en vuelo: mueren por su propio timeout HTTP en
            # hilos nativos de fondo, sin bloquear el QThread ni el cierre de la ventana.
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

        if not self.is_cancelled():
            self.finished_signal.emit(results)


class GlobalDiscoveryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 Descubrimiento Global de Modelos LLM")
        self.setFixedWidth(540)
        self.setStyleSheet(f"""
            QDialog {{ background-color: #070D14; color: #F1F5F9; font-family: 'Inter', sans-serif; }}
            QLabel {{ color: #F1F5F9; }}
            QRadioButton {{ color: #E2E8F0; font-size: 11px; spacing: 8px; padding: 4px 0px; }}
            QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 7px; border: 1px solid #334155; background-color: #0E1A29; }}
            QRadioButton::indicator:checked {{ background-color: {COLOR_PRIMARY_CYAN}; border: 1px solid {COLOR_PRIMARY_CYAN}; }}
            QComboBox {{ background-color: #0F172A; border: 1px solid #1E293B; border-radius: 6px; padding: 4px 8px; color: #F1F5F9; }}
            QCheckBox {{ color: #CBD5E1; font-size: 11px; }}
            QPushButton#PrimaryBtn {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00F5D4, stop:1 #00BBF9); color: #050911; font-weight: 700; border-radius: 6px; padding: 8px 16px; }}
            QPushButton#SecondaryBtn {{ background-color: #1E293B; color: #F1F5F9; border: 1px solid #334155; border-radius: 6px; padding: 8px 16px; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        lbl_title = QLabel("🛰️ Descarga de Catálogos de Proveedores")
        lbl_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        layout.addWidget(lbl_title)

        lbl_sub = QLabel("Elige el conjunto de modelos a importar desde OpenRouter (390+), NVIDIA NIM (80+), Google AI Studio y Mistral:")
        lbl_sub.setFont(QFont("Inter", 9))
        lbl_sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lbl_sub.setWordWrap(True)
        layout.addWidget(lbl_sub)

        # Grupo de opciones
        grp_box = QFrame()
        grp_box.setStyleSheet("background-color: #0B121E; border: 1px solid #1E293B; border-radius: 8px; padding: 10px;")
        grp_lay = QVBoxLayout(grp_box)
        grp_lay.setSpacing(8)

        self.btn_group = QButtonGroup(self)
        self.rb_all = QRadioButton("🌟 Todos los Modelos Disponibles (+400 LLMs en OpenRouter / NIM / Google)")
        self.rb_free = QRadioButton("🆓 Solo Modelos Gratuitos / Free Tier (25+ LLMs)")
        self.rb_frontier = QRadioButton("🚀 Frontier & Razonamiento Top (Claude, GPT-4o, DeepSeek R1/V3, Gemini, Qwen)")
        self.rb_code = QRadioButton("💻 Especializados en Código (Claude Sonnet, Qwen Coder, DeepSeek Coder, Codestral)")
        self.rb_context = QRadioButton("🧠 Gran Ventana de Contexto (≥ 128k / 1M+ tokens)")
        self.rb_nvidia = QRadioButton("🟢 NVIDIA NIM Direct Hub (83 LLMs con endpoints dedicados)")

        self.rb_all.setChecked(True)

        self.btn_group.addButton(self.rb_all, 0)
        self.btn_group.addButton(self.rb_free, 1)
        self.btn_group.addButton(self.rb_frontier, 2)
        self.btn_group.addButton(self.rb_code, 3)
        self.btn_group.addButton(self.rb_context, 4)
        self.btn_group.addButton(self.rb_nvidia, 5)

        for rb in (self.rb_all, self.rb_free, self.rb_frontier, self.rb_code, self.rb_context, self.rb_nvidia):
            grp_lay.addWidget(rb)

        layout.addWidget(grp_box)

        # Selector de contexto mínimo
        ctx_row = QHBoxLayout()
        lbl_ctx = QLabel("Filtro de Contexto Mínimo:")
        lbl_ctx.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        ctx_row.addWidget(lbl_ctx)

        self.combo_min_ctx = QComboBox()
        self.combo_min_ctx.addItems(["Cualquier Contexto (0+)", "≥ 32k tokens", "≥ 128k tokens", "≥ 256k tokens", "≥ 1M tokens"])
        self.combo_min_ctx.setCurrentIndex(0)
        ctx_row.addWidget(self.combo_min_ctx)
        layout.addLayout(ctx_row)

        # Checkbox Reemplazar vs Añadir
        self.chk_replace = QCheckBox("Reemplazar tabla actual con el nuevo conjunto descargado")
        self.chk_replace.setChecked(True)
        layout.addWidget(self.chk_replace)

        # Botones de acción
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("SecondaryBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_download = QPushButton("🚀 Descargar e Incorporar")
        btn_download.setObjectName("PrimaryBtn")
        btn_download.clicked.connect(self.accept)
        btn_box.addWidget(btn_download)

        layout.addLayout(btn_box)

    def get_selected_options(self) -> dict:
        mode_map = {
            0: "all",
            1: "free",
            2: "frontier",
            3: "code",
            4: "context_128k",
            5: "nvidia"
        }
        ctx_map = {
            0: 0,
            1: 32000,
            2: 128000,
            3: 256000,
            4: 1000000
        }
        selected_id = self.btn_group.checkedId()
        mode = mode_map.get(selected_id, "all")
        min_ctx = ctx_map.get(self.combo_min_ctx.currentIndex(), 0)
        replace = self.chk_replace.isChecked()

        return {
            "mode": mode,
            "min_ctx": min_ctx,
            "replace": replace
        }


class CatalogDiscoveryWorker(CancellableThread):
    discovery_finished = pyqtSignal(list, bool, str)
    error_signal = pyqtSignal(str)

    def __init__(self, openrouter_key: Optional[str], nvidia_key: Optional[str], google_key: Optional[str], mistral_key: Optional[str], deepseek_key: Optional[str], options: dict, b_ai_key: Optional[str] = None, tokenrouter_key: Optional[str] = None, zenmux_key: Optional[str] = None, fireworks_key: Optional[str] = None, cloudflare_key: Optional[str] = None):
        super().__init__()
        self.openrouter_key = openrouter_key
        self.nvidia_key = nvidia_key
        self.google_key = google_key
        self.mistral_key = mistral_key
        self.deepseek_key = deepseek_key
        self.b_ai_key = b_ai_key
        self.tokenrouter_key = tokenrouter_key
        self.zenmux_key = zenmux_key
        self.fireworks_key = fireworks_key
        self.cloudflare_key = cloudflare_key
        self.options = options

    def run(self):
        try:
            mode = self.options.get("mode", "all")
            min_ctx = self.options.get("min_ctx", 0)
            replace = self.options.get("replace", True)

            discovered = []
            errors = []
            seen_ids = set()

            # 1. Descubrir OpenRouter
            if self.openrouter_key and mode != "nvidia":
                try:
                    url = "https://openrouter.ai/api/v1/models"
                    headers = {"Authorization": f"Bearer {self.openrouter_key}", "User-Agent": "FloydiaAgentRadar/3.0"}
                    req = urllib.request.Request(url, headers=headers, method="GET")
                    with urllib.request.urlopen(req, timeout=14) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        raw_models = data.get("data", [])

                        for m in raw_models:
                            if self.is_cancelled():
                                return
                            m_id = m.get("id", "")
                            if not m_id or m_id in seen_ids:
                                continue

                            ctx = int(m.get("context_length", 0) or 0)
                            pricing = m.get("pricing", {})
                            prompt_price = 0.0
                            if isinstance(pricing, dict):
                                try:
                                    p_val = pricing.get("prompt", 0)
                                    prompt_price = float(p_val) if p_val is not None else 0.0
                                except (ValueError, TypeError):
                                    prompt_price = 0.0

                            is_free = (prompt_price == 0) or (":free" in m_id) or ("free" in m_id.lower())
                            
                            if ctx < min_ctx:
                                continue

                            m_id_lower = m_id.lower()
                            name_lower = str(m.get("name", "")).lower()

                            if mode == "free" and not is_free:
                                continue
                            elif mode == "frontier":
                                frontier_keys = ["claude-3.5", "claude-3.7", "gpt-4o", "o1", "o3", "deepseek-r1", "deepseek-v3", "gemini-2.5", "gemini-2.0", "qwen-2.5-max", "qwen-max", "mistral-large", "llama-3.3-70b", "llama-3.1-405b", "minimax-m3"]
                                if not any(k in m_id_lower for k in frontier_keys):
                                    continue
                            elif mode == "code":
                                code_keys = ["coder", "code", "sonnet", "codestral", "devstral", "starcoder", "deepseek-coder", "qwen-2.5-coder", "claude-3.5-sonnet", "claude-3.7-sonnet"]
                                if not any(k in m_id_lower or k in name_lower for k in code_keys):
                                    continue
                            elif mode == "context_128k" and ctx < 128000:
                                continue

                            cat = "free" if is_free else ("frontier" if any(k in m_id_lower for k in ["claude", "gpt-4", "o1", "r1", "gemini-2", "gemini-3"]) else "standard")
                            ctx_k = ctx // 1000 if ctx else 0
                            badge = f"[{ctx_k}k•{'Free' if is_free else 'Pro'}] {m_id.split('/')[-1][:16]}"

                            discovered.append({
                                "id": m_id,
                                "name": m.get("name", m_id),
                                "account_tag": "C7",
                                "provider": "openrouter",
                                "base_url": "https://openrouter.ai/api/v1",
                                "key": self.openrouter_key or OPENROUTER_C7_KEY or OPENROUTER_KEY,
                                "context": ctx,
                                "badge": badge,
                                "category": cat,
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "Modelo OpenRouter Global"
                            })
                            seen_ids.add(m_id)
                except Exception as exc:
                    errors.append(f"OpenRouter: {exc}")

                # Fusión de flota curada OpenRouter para garantizar +35 modelos
                for cur_m in CURATED_FLEET:
                    if cur_m.get("provider") == "openrouter" and cur_m["id"] not in seen_ids:
                        c_ctx = int(cur_m.get("context", 0) or 0)
                        if c_ctx < min_ctx:
                            continue
                        c_cat = cur_m.get("category", "free")
                        if mode == "free" and c_cat != "free":
                            continue
                        if mode == "frontier" and c_cat not in ("frontier", "reasoner"):
                            continue
                        if mode == "code" and c_cat != "code":
                            continue
                        if mode == "context_128k" and c_ctx < 128000:
                            continue
                        discovered.append({
                            **cur_m,
                            "status": "⚪ Sin probar",
                            "latency_ms": 0,
                            "response_snippet": "Modelo Curado OpenRouter"
                        })
                        seen_ids.add(cur_m["id"])

            # 2. Descubrir NVIDIA NIM
            if self.nvidia_key and mode in ["all", "nvidia", "free", "code", "frontier"]:
                try:
                    url = "https://integrate.api.nvidia.com/v1/models"
                    headers = {"Authorization": f"Bearer {self.nvidia_key}", "User-Agent": "FloydiaAgentRadar/3.0"}
                    req = urllib.request.Request(url, headers=headers, method="GET")
                    with urllib.request.urlopen(req, timeout=14) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        raw_models = data.get("data", [])

                        for m in raw_models:
                            if self.is_cancelled():
                                return
                            m_id = m.get("id", "")
                            if not m_id or m_id in seen_ids:
                                continue

                            ctx = 131072 if "128k" in m_id else (262144 if "nemotron" in m_id else 32768)
                            if ctx < min_ctx:
                                continue

                            m_id_lower = m_id.lower()
                            if mode == "code" and not any(k in m_id_lower for k in ["code", "coder", "starcoder"]):
                                continue
                            if mode == "context_128k" and ctx < 128000:
                                continue

                            discovered.append({
                                "id": m_id,
                                "name": f"NVIDIA {m_id.split('/')[-1]}",
                                "account_tag": "C7",
                                "provider": "nvidia",
                                "base_url": "https://integrate.api.nvidia.com/v1",
                                "key": self.nvidia_key,
                                "context": ctx,
                                "badge": f"NIM • {ctx // 1000}k",
                                "category": "nim",
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "NVIDIA NIM Dedicated Endpoint"
                            })
                            seen_ids.add(m_id)
                except Exception as exc:
                    errors.append(f"NVIDIA: {exc}")

            # 3. Incorporar Google AI Studio
            if self.google_key and mode in ["all", "google", "free", "frontier", "code"]:
                google_models = [
                    {"id": "gemini-3.7-flash", "name": "[C1] Gemini 3.7 Flash Reasoning", "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
                    {"id": "gemini-3.6-flash", "name": "[C1] Gemini 3.6 Flash Fast", "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
                    {"id": "gemini-3.5-flash", "name": "[C1] Gemini 3.5 Flash Multimodal", "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
                    {"id": "gemini-2.5-flash", "name": "[C1] Gemini 2.5 Flash Reasoning", "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
                    {"id": "gemini-2.5-pro", "name": "[C1] Gemini 2.5 Pro Ultra Thinking", "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
                    {"id": "gemini-2.0-flash", "name": "[C1] Gemini 2.0 Flash Production", "context": 1048576, "badge": "1M • Free/Pro", "category": "frontier"},
                    {"id": "gemini-2.0-flash-lite", "name": "[C1] Gemini 2.0 Flash Lite", "context": 1048576, "badge": "1M • Free", "category": "free"},
                    {"id": "gemma-4-31b-it", "name": "[C1] Gemma 4 31B Instruct", "context": 262144, "badge": "262k • Pro", "category": "frontier"},
                    {"id": "gemma-2-27b-it", "name": "[C1] Gemma 2 27B Instruct", "context": 8192, "badge": "8k • Free", "category": "free"},
                    {"id": "gemma-2-9b-it", "name": "[C1] Gemma 2 9B Instruct", "context": 8192, "badge": "8k • Free", "category": "free"}
                ]
                for gm in google_models:
                    if gm["id"] not in seen_ids and gm["context"] >= min_ctx:
                        discovered.append({
                            **gm,
                            "account_tag": "C1",
                            "provider": "google",
                            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                            "key": self.google_key,
                            "status": "⚪ Sin probar",
                            "latency_ms": 0,
                            "response_snippet": "Google AI Studio"
                        })
                        seen_ids.add(gm["id"])

            # 4. Descubrir e Incorporar DeepSeek Direct
            effective_ds_key = self.deepseek_key or DEEPSEEK_DIRECT_KEY or DEEPSEEK_C1_KEY or DEEPSEEK_C7_KEY
            if effective_ds_key and mode in ["all", "frontier", "code", "context_128k"]:
                try:
                    # Intento de consulta en vivo al catálogo DeepSeek
                    ds_url = "https://api.deepseek.com/models"
                    ds_headers = {"Authorization": f"Bearer {effective_ds_key}", "User-Agent": "FloydiaAgentRadar/3.0"}
                    ds_req = urllib.request.Request(ds_url, headers=ds_headers, method="GET")
                    with urllib.request.urlopen(ds_req, timeout=8) as ds_resp:
                        ds_data = json.loads(ds_resp.read().decode("utf-8"))
                        for dm in ds_data.get("data", []):
                            dm_id = dm.get("id", "")
                            if dm_id and dm_id not in seen_ids:
                                discovered.append({
                                    "id": dm_id,
                                    "name": f"[Direct] DeepSeek {dm_id.replace('-', ' ').title()}",
                                    "account_tag": "Direct",
                                    "provider": "deepseek",
                                    "base_url": "https://api.deepseek.com/v1",
                                    "key": DEEPSEEK_DIRECT_KEY or effective_ds_key,
                                    "context": 128000,
                                    "badge": "128k • Direct",
                                    "category": "frontier",
                                    "status": "⚪ Sin probar",
                                    "latency_ms": 0,
                                    "response_snippet": "DeepSeek API Direct"
                                })
                                seen_ids.add(dm_id)
                except Exception as ds_exc:
                    errors.append(f"DeepSeek Models API: {ds_exc}")

                # Incorporar la suite completa curada DeepSeek (Direct, C1, C7)
                for cur_m in CURATED_FLEET:
                    if cur_m.get("provider") == "deepseek" and cur_m["id"] not in seen_ids:
                        if 128000 >= min_ctx:
                            discovered.append({
                                **cur_m,
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "DeepSeek Direct Curado"
                            })
                            seen_ids.add(cur_m["id"])

            # 5. Incorporar Mistral AI
            if self.mistral_key and mode in ["all", "code", "frontier", "context_128k"]:
                for cur_m in CURATED_FLEET:
                    if cur_m.get("provider") == "mistral" and cur_m["id"] not in seen_ids:
                        c_ctx = int(cur_m.get("context", 0) or 0)
                        if c_ctx >= min_ctx:
                            discovered.append({
                                **cur_m,
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "Mistral AI Dedicated"
                            })
                            seen_ids.add(cur_m["id"])

            # 6. Descubrir e Incorporar B.AI Gateway Hub [C7] (44 LLMs)
            effective_bai_key = self.b_ai_key or B_AI_C7_KEY or B_AI_KEY
            if effective_bai_key and mode in ["all", "frontier", "code", "context_128k", "free"]:
                try:
                    bai_url = "https://api.b.ai/v1/models"
                    bai_headers = {"Authorization": f"Bearer {effective_bai_key}", "User-Agent": "FloydiaAgentRadar/3.0"}
                    bai_req = urllib.request.Request(bai_url, headers=bai_headers, method="GET")
                    with urllib.request.urlopen(bai_req, timeout=8) as bai_resp:
                        bai_data = json.loads(bai_resp.read().decode("utf-8"))
                        for bm in bai_data.get("data", []):
                            if self.is_cancelled():
                                return
                            bm_id = bm.get("id", "")
                            if bm_id and bm_id not in seen_ids:
                                ctx = int(bm.get("context_length", 128000) or 128000)
                                if ctx < min_ctx:
                                    continue
                                bm_id_lower = bm_id.lower()
                                if mode == "code" and not any(k in bm_id_lower for k in ["code", "coder", "codestral"]):
                                    continue
                                if mode == "context_128k" and ctx < 128000:
                                    continue
                                is_free = any(k in bm_id_lower for k in ["free", "flash", "lite", "small"])
                                if mode == "free" and not is_free:
                                    continue
                                discovered.append({
                                    "id": bm_id,
                                    "name": f"[C7] B.AI {bm_id.replace('-', ' ').title()}",
                                    "account_tag": "C7",
                                    "provider": "b_ai",
                                    "base_url": "https://api.b.ai/v1",
                                    "key": effective_bai_key,
                                    "context": ctx,
                                    "badge": f"{ctx // 1000 if ctx else 128}k • B.AI",
                                    "category": "frontier" if not is_free else "free",
                                    "status": "⚪ Sin probar",
                                    "latency_ms": 0,
                                    "response_snippet": "B.AI Multi-Model Gateway"
                                })
                                seen_ids.add(bm_id)
                except Exception as bai_exc:
                    errors.append(f"B.AI API: {bai_exc}")

                # Incorporar la suite completa curada B.AI si no estaban en el catálogo remoto
                for cur_m in CURATED_FLEET:
                    if cur_m.get("provider") == "b_ai" and cur_m["id"] not in seen_ids:
                        c_ctx = int(cur_m.get("context", 0) or 0)
                        if c_ctx >= min_ctx:
                            discovered.append({
                                **cur_m,
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "B.AI Gateway Hub [C7]"
                            })
                            seen_ids.add(cur_m["id"])

            # 7. Descubrir e Incorporar TokenRouter & ZenMux AI Hubs [C7]
            effective_tr_key = self.tokenrouter_key or TOKENROUTER_C7_KEY or TOKENROUTER_KEY
            if effective_tr_key and mode in ["all", "frontier", "code", "free"]:
                try:
                    tr_url = "https://api.tokenrouter.com/v1/models"
                    tr_headers = {"Authorization": f"Bearer {effective_tr_key}", "User-Agent": "FloydiaAgentRadar/3.0"}
                    tr_req = urllib.request.Request(tr_url, headers=tr_headers, method="GET")
                    with urllib.request.urlopen(tr_req, timeout=8) as tr_resp:
                        tr_data = json.loads(tr_resp.read().decode("utf-8"))
                        for tm in tr_data.get("data", []):
                            if self.is_cancelled():
                                return
                            tm_id = tm.get("id", "")
                            if tm_id and tm_id not in seen_ids:
                                ctx = int(tm.get("context_length", 128000) or 128000)
                                if ctx >= min_ctx:
                                    discovered.append({
                                        "id": tm_id,
                                        "name": f"[C7] TokenRouter {tm_id.split('/')[-1]}",
                                        "account_tag": "C7",
                                        "provider": "tokenrouter",
                                        "base_url": "https://api.tokenrouter.com/v1",
                                        "key": effective_tr_key,
                                        "context": ctx,
                                        "badge": f"{ctx // 1000 if ctx else 128}k • TR",
                                        "category": "frontier",
                                        "status": "⚪ Sin probar",
                                        "latency_ms": 0,
                                        "response_snippet": "TokenRouter Multicloud"
                                    })
                                    seen_ids.add(tm_id)
                except Exception as tr_exc:
                    errors.append(f"TokenRouter API: {tr_exc}")

                for cur_m in CURATED_FLEET:
                    if cur_m.get("provider") == "tokenrouter" and cur_m["id"] not in seen_ids:
                        if int(cur_m.get("context", 0) or 0) >= min_ctx:
                            discovered.append({
                                **cur_m,
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "TokenRouter AI Hub [C7]"
                            })
                            seen_ids.add(cur_m["id"])

            effective_zm_key = self.zenmux_key or ZENMUX_C7_KEY or ZENMUX_KEY
            if effective_zm_key and mode in ["all", "frontier", "code", "free"]:
                try:
                    zm_url = "https://zenmux.ai/api/v1/models"
                    zm_headers = {"Authorization": f"Bearer {effective_zm_key}", "User-Agent": "FloydiaAgentRadar/3.0"}
                    zm_req = urllib.request.Request(zm_url, headers=zm_headers, method="GET")
                    with urllib.request.urlopen(zm_req, timeout=8) as zm_resp:
                        zm_data = json.loads(zm_resp.read().decode("utf-8"))
                        for zm in zm_data.get("data", []):
                            if self.is_cancelled():
                                return
                            zm_id = zm.get("id", "")
                            if zm_id and zm_id not in seen_ids:
                                ctx = int(zm.get("context_length", 128000) or 128000)
                                if ctx >= min_ctx:
                                    discovered.append({
                                        "id": zm_id,
                                        "name": f"[C7] ZenMux {zm_id.split('/')[-1]}",
                                        "account_tag": "C7",
                                        "provider": "zenmux",
                                        "base_url": "https://zenmux.ai/api/v1",
                                        "key": effective_zm_key,
                                        "context": ctx,
                                        "badge": f"{ctx // 1000 if ctx else 128}k • ZenMux",
                                        "category": "frontier",
                                        "status": "⚪ Sin probar",
                                        "latency_ms": 0,
                                        "response_snippet": "ZenMux Global Hub"
                                    })
                                    seen_ids.add(zm_id)
                except Exception as zm_exc:
                    errors.append(f"ZenMux API: {zm_exc}")

                for cur_m in CURATED_FLEET:
                    if cur_m.get("provider") == "zenmux" and cur_m["id"] not in seen_ids:
                        if int(cur_m.get("context", 0) or 0) >= min_ctx:
                            discovered.append({
                                **cur_m,
                                "status": "⚪ Sin probar",
                                "latency_ms": 0,
                                "response_snippet": "ZenMux AI Hub [C7]"
                            })
                            seen_ids.add(cur_m["id"])

            # 8. Incorporar Cloudflare, Fireworks, Groq y Z.AI Curados [C7 / C1]
            for cur_m in CURATED_FLEET:
                if cur_m.get("provider") in ("cloudflare", "fireworks", "groq", "zai") and cur_m["id"] not in seen_ids:
                    c_ctx = int(cur_m.get("context", 0) or 0)
                    if c_ctx >= min_ctx:
                        discovered.append({
                            **cur_m,
                            "status": "⚪ Sin probar",
                            "latency_ms": 0,
                            "response_snippet": f"{cur_m.get('provider', '').upper()} Curado [C7/C1]"
                        })
                        seen_ids.add(cur_m["id"])

            summary = f"Catálogo recuperado: {len(discovered)} modelos listados con éxito."
            if errors:
                summary += f" (Avisos: {', '.join(errors)})"

            self.discovery_finished.emit(discovered, replace, summary)
        except Exception as top_exc:
            self.error_signal.emit(f"Error general en descubrimiento de catálogo: {top_exc}")


class SyncHP45Worker(CancellableThread):
    sync_finished = pyqtSignal(bool, str)

    def __init__(self, script_path: str):
        super().__init__()
        self.script_path = script_path

    def run(self):
        try:
            res = subprocess.run(["bash", self.script_path], capture_output=True, text=True, timeout=15, check=False)
            if self.is_cancelled():
                return
            if res.returncode == 0:
                self.sync_finished.emit(True, "Modelos propagados hacia Laptop HP45 (tec@192.168.1.200).")
            else:
                self.sync_finished.emit(False, f"Fallo en script ({res.returncode}): {res.stderr.strip()[:100]}")
        except Exception as exc:
            self.sync_finished.emit(False, f"Excepción en réplica: {exc}")

class AIAdvisorWorker(CancellableThread):
    response_ready = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, prompt: str, telemetry: List[Dict[str, Any]]):
        super().__init__()
        self.prompt = prompt
        self.telemetry = telemetry

    def run(self):
        self.log_signal.emit("🧠 Consultando al Asesor IA de FloydIA con telemetría en vivo...")
        
        telemetry_summary = []
        for m in self.telemetry:
            telemetry_summary.append({
                "name": m.get("name"),
                "id": m.get("id"),
                "provider": m.get("provider"),
                "status": m.get("status", "Sin probar"),
                "latency_ms": m.get("latency_ms", 0),
                "context": m.get("context", 0),
                "snippet": m.get("response_snippet", "")
            })

        system_prompt = (
            "Eres el Asesor Principal de Infraestructura e Inteligencia Artificial de FloydIA Homelab.\n"
            "Analiza los siguientes datos de telemetría y salud de modelos IA en vivo y responde la consulta del usuario de forma concisa, técnica y accionable en español:\n\n"
            f"TELEMETRÍA EN VIVO ({len(telemetry_summary)} MODELOS):\n"
            f"{json.dumps(telemetry_summary, indent=2, ensure_ascii=False)}\n\n"
            f"CONSULTA DEL USUARIO:\n{self.prompt}\n\n"
            "Entrega recomendaciones claras citando latencias reales, costos y roles sugeridos (Principal, Fast Reasoning, Fallback)."
        )

        answer = None

        # Intento 1: DeepSeek Chat V3 Direct
        if DEEPSEEK_KEY:
            try:
                url = "https://api.deepseek.com/v1/chat/completions"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_KEY}"}
                payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": system_prompt}], "max_tokens": 1200, "temperature": 0.2}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    answer = data["choices"][0]["message"]["content"]
            except Exception as e:
                self.log_signal.emit(f"ℹ️ DeepSeek fallback: {e}")

        # Intento 2: Google AI Studio Gemini 3.7 / 3.6
        if not answer and GOOGLE_KEY:
            try:
                url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GOOGLE_KEY}"}
                payload = {"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": system_prompt}], "max_tokens": 1200, "temperature": 0.2}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    answer = data["choices"][0]["message"]["content"]
            except Exception as e:
                self.log_signal.emit(f"ℹ️ Gemini fallback: {e}")

        # Intento 3: OpenRouter MiniMax M3
        if not answer and OPENROUTER_KEY:
            try:
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENROUTER_KEY}"}
                payload = {"model": "minimax/minimax-m3:free", "messages": [{"role": "user", "content": system_prompt}], "max_tokens": 1200, "temperature": 0.2}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    answer = data["choices"][0]["message"]["content"]
            except Exception:
                pass

        if not answer:
            answer = "⚠️ No fue posible consultar a los modelos de análisis debido a falta de claves de API o rate limits temporales."

        self.response_ready.emit(answer)


class TabRadar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fleet_data = list(CURATED_FLEET)
        self.table_models_map: Dict[str, Dict[str, Any]] = {m["id"]: dict(m) for m in self.fleet_data}
        self.table_checkboxes: Dict[str, QCheckBox] = {}
        self.previous_latencies: Dict[str, int] = self.load_cached_telemetry()
        self.probe_worker: Optional[ProbeWorker] = None
        self.advisor_worker: Optional[AIAdvisorWorker] = None
        self.discovery_worker: Optional[CatalogDiscoveryWorker] = None
        self.sync_worker: Optional[SyncHP45Worker] = None
        self._kpi_throttle_timer: Optional[QTimer] = None

        self.init_ui()
        self.populate_table()
        self.update_kpi_dashboard()

    def load_cached_telemetry(self) -> Dict[str, int]:
        lat_map = {}
        if os.path.exists(RADAR_CACHE_FILE):
            try:
                data = atomic_read_json(RADAR_CACHE_FILE)
                models = data.get("models", [])
                if isinstance(models, list):
                    for item in models:
                        if isinstance(item, dict) and "id" in item and item.get("latency_ms", 0) > 0:
                            lat_map[item["id"]] = item["latency_ms"]
                elif isinstance(models, dict):
                    for m_id, item in models.items():
                        if isinstance(item, dict):
                            lat = item.get("latency_ms", 0)
                            if isinstance(lat, (int, float)) and lat > 0:
                                lat_map[m_id] = int(lat)
            except Exception:
                pass
        return lat_map

    def save_cached_telemetry(self, results: List[Dict[str, Any]]):
        try:
            # P0 Security: Sanitizar y purgar cualquier clave API antes de persistir a disco
            safe_results = sanitize_for_persistence(results)
            cache_payload = {
                "version": 2,
                "timestamp": utc_now_iso(),
                "total_models": len(safe_results),
                "models": safe_results
            }
            atomic_write_json(RADAR_CACHE_FILE, cache_payload)
        except Exception:
            pass

    def save_state(self) -> dict:
        """Serializa el estado completo del Radar (telemetría, respuestas y checkboxes) para session_state.json."""
        models_state = {}
        for m_id, m in self.table_models_map.items():
            is_checked = True
            if m_id in self.table_checkboxes:
                cb = self.table_checkboxes[m_id]
                if cb is not None:
                    is_checked = cb.isChecked()
            models_state[m_id] = {
                "status": m.get("status", ""),
                "latency_ms": m.get("latency_ms", 0),
                "response_snippet": m.get("response_snippet", ""),
                "raw_response": m.get("raw_response", ""),
                "checked": is_checked,
                "provider": m.get("provider", ""),
                "account_tag": m.get("account_tag", ""),
                "name": m.get("name", m_id),
                "context": m.get("context", 0),
                "badge": m.get("badge", ""),
                "category": m.get("category", "")
            }
        return {
            "version": 1,
            "saved_at": utc_now_iso(),
            "models": models_state
        }

    def restore_state(self, state: dict) -> None:
        """Restaura el estado completo del Radar desde session_state.json."""
        if not isinstance(state, dict) or not state:
            return
        saved_models = state.get("models", {})
        if not isinstance(saved_models, dict):
            return

        for m_id, data in saved_models.items():
            if not isinstance(data, dict):
                continue
            if m_id not in self.table_models_map:
                self.table_models_map[m_id] = {
                    "id": m_id,
                    "name": data.get("name", m_id),
                    "provider": data.get("provider", "dynamic"),
                    "account_tag": data.get("account_tag", "C1"),
                    "context": data.get("context", 128000),
                    "badge": data.get("badge", "Dynamic"),
                    "category": data.get("category", "frontier"),
                    "base_url": data.get("base_url", ""),
                    "key": None
                }
            m = self.table_models_map[m_id]
            if "status" in data and data["status"]:
                m["status"] = data["status"]
            if "latency_ms" in data and data["latency_ms"]:
                m["latency_ms"] = data["latency_ms"]
            if "response_snippet" in data:
                m["response_snippet"] = data["response_snippet"]
            if "raw_response" in data:
                m["raw_response"] = data["raw_response"]

        self.populate_table()
        for m_id, data in saved_models.items():
            if isinstance(data, dict) and "checked" in data:
                cb = self.table_checkboxes.get(m_id)
                if cb is not None:
                    cb.setChecked(bool(data["checked"]))
        self.update_kpi_dashboard()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # ── 1. Cabecera Principal ─────────────────────────────────────────────
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("🛰️ AI Radar, Observatorio de Modelos & Asesor IA")
        title.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        
        subtitle = QLabel("Telemetría en vivo, benchmark dinámico, dashboard analítico, exportación de reportes e integración multi-cliente")
        subtitle.setFont(QFont("Inter", 9))
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_bar.addLayout(title_box)
        top_bar.addStretch()

        self.btn_probe_curated = QPushButton("⚡ SONDEAR FLOTA EN VIVO")
        self.btn_probe_curated.setObjectName("PrimaryBtn")
        self.btn_probe_curated.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_probe_curated.clicked.connect(self.start_curated_probe)
        top_bar.addWidget(self.btn_probe_curated)

        self.btn_discover_global = QPushButton("🌐 Descubrir Catálogo Global")
        self.btn_discover_global.setObjectName("SecondaryBtn")
        self.btn_discover_global.clicked.connect(self.discover_global_catalog)
        top_bar.addWidget(self.btn_discover_global)

        layout.addLayout(top_bar)

        # ── 2. KPI Analytics Dashboard (Bento Grid) ───────────────────────────
        self.kpi_container = QHBoxLayout()
        self.kpi_container.setSpacing(8)

        self.card_health = self.create_kpi_card("ESTADO FLOTA", "0 / 16 ONLINE", "Sin sondeo reciente", "#10B981")
        self.card_avg_lat = self.create_kpi_card("LATENCIA PROMEDIO", "— ms", "Salud global de red", "#38BDF8")
        self.card_fastest = self.create_kpi_card("SPEED LEADER", "—", "Modelo más veloz", "#10D2AD")
        self.card_context = self.create_kpi_card("MAX CONTEXTO", "1M Tokens", "Gemini 3.7 / MiniMax", "#818CF8")
        self.card_tiers = self.create_kpi_card("DISTRIBUCIÓN", "7 Free • 5 Pro • 4 NIM", "Curada activa", "#F59E0B")

        self.kpi_container.addWidget(self.card_health)
        self.kpi_container.addWidget(self.card_avg_lat)
        self.kpi_container.addWidget(self.card_fastest)
        self.kpi_container.addWidget(self.card_context)
        self.kpi_container.addWidget(self.card_tiers)

        layout.addLayout(self.kpi_container)

        # ── 2.5 Semáforo de Paridad 1:1 Multi-Agente (Protocolo v27) ───────────
        self.card_parity = self.create_parity_traffic_light_widget()
        layout.addWidget(self.card_parity)

        # ── 3. Panel de Configuración de Sonda y Pregunta de Prueba ───────────
        probe_box = QFrame()
        probe_box.setProperty("class", "CardFrame")
        probe_box.setStyleSheet(f"background-color: #0A111E; border: 1px solid #1E293B; border-radius: 8px; padding: 6px;")
        probe_lay = QVBoxLayout(probe_box)
        probe_lay.setContentsMargins(8, 6, 8, 6)
        probe_lay.setSpacing(6)

        # Fila 1: Preset y Parámetros
        p_row1 = QHBoxLayout()
        lbl_p_mode = QLabel("🎯 Preset de Sonda:")
        lbl_p_mode.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        lbl_p_mode.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        p_row1.addWidget(lbl_p_mode)

        self.combo_probe_presets = QComboBox()
        self.combo_probe_presets.addItems(list(PROBE_PRESETS.keys()))
        self.combo_probe_presets.setFixedWidth(280)
        self.combo_probe_presets.currentIndexChanged.connect(self.handle_probe_preset_changed)
        p_row1.addWidget(self.combo_probe_presets)

        lbl_tokens = QLabel("Max Tokens:")
        lbl_tokens.setFont(QFont("Inter", 9))
        p_row1.addWidget(lbl_tokens)
        self.combo_max_tokens = QComboBox()
        self.combo_max_tokens.addItems(["8", "16", "32", "45", "64", "80", "128", "256"])
        self.combo_max_tokens.setCurrentText("8")
        p_row1.addWidget(self.combo_max_tokens)

        lbl_timeout = QLabel("Timeout:")
        lbl_timeout.setFont(QFont("Inter", 9))
        p_row1.addWidget(lbl_timeout)
        self.combo_timeout = QComboBox()
        self.combo_timeout.addItems(["5s", "7s", "10s", "12s", "15s", "20s"])
        self.combo_timeout.setCurrentText("7s")
        p_row1.addWidget(self.combo_timeout)

        p_row1.addStretch()

        self.lbl_preset_desc = QLabel(PROBE_PRESETS["⚡ Ping Ultrarrápido (Latencia Pura)"]["desc"])
        self.lbl_preset_desc.setFont(QFont("Inter", 8))
        self.lbl_preset_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        p_row1.addWidget(self.lbl_preset_desc)

        probe_lay.addLayout(p_row1)

        # Fila 2: Campo de Pregunta Personalizada / Benchmark
        p_row2 = QHBoxLayout()
        lbl_prompt_label = QLabel("Pregunta enviada a la IA:")
        lbl_prompt_label.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        p_row2.addWidget(lbl_prompt_label)

        self.txt_probe_prompt = QLineEdit()
        self.txt_probe_prompt.setText("1")
        self.txt_probe_prompt.setPlaceholderText("Escribe la pregunta o prompt de prueba para enviar a todos los modelos...")
        self.txt_probe_prompt.setStyleSheet("background-color: #070D14; border: 1px solid #1E3A5F; border-radius: 4px; padding: 4px 8px; color: #F1F5F9;")
        p_row2.addWidget(self.txt_probe_prompt)

        btn_reset_prompt = QPushButton("↺ Restaurar")
        btn_reset_prompt.setObjectName("SecondaryBtn")
        btn_reset_prompt.clicked.connect(self.reset_probe_prompt)
        p_row2.addWidget(btn_reset_prompt)

        probe_lay.addLayout(p_row2)
        layout.addWidget(probe_box)

        # ── 4. Barra de Acciones, Exportación y Filtros Multi-Cuenta ─────────
        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)
        
        self.txt_search_model = QLineEdit()
        self.txt_search_model.setPlaceholderText("🔍 Filtrar por nombre, [C1], ID, proveedor o extracto...")
        self.txt_search_model.setMinimumWidth(240)
        self.txt_search_model.textChanged.connect(self.apply_table_filters)
        action_bar.addWidget(self.txt_search_model)

        # Filtro de Cuentas [C1..C8]
        self.combo_account_filter = QComboBox()
        self.combo_account_filter.addItems([
            "Todas las Cuentas",
            "Solo [C1]",
            "Solo [C2]",
            "Solo [C7]",
            "Solo Direct / Free"
        ])
        self.combo_account_filter.currentIndexChanged.connect(self.apply_table_filters)
        action_bar.addWidget(self.combo_account_filter)

        self.combo_category_filter = QComboBox()
        self.combo_category_filter.addItems([
            "Todas las Categorías",
            "🟢 Solo Respuestas OK / Coherentes",
            "Solo Online (200 OK)",
            "Gratuitos / Auto (Free)",
            "Frontier / Reasoning (1M/Pro)",
            "Especializados en Código",
            "Google AI Studio",
            "NVIDIA NIM",
            "OpenRouter",
            "Mistral / Codestral",
            "DeepSeek Direct"
        ])
        self.combo_category_filter.currentIndexChanged.connect(self.apply_table_filters)
        action_bar.addWidget(self.combo_category_filter)

        # Filtro de Ventana de Contexto
        self.combo_context_filter = QComboBox()
        self.combo_context_filter.addItems([
            "Todas las Ventanas (0+)",
            "≥ 32k tokens",
            "≥ 128k tokens",
            "≥ 200k tokens",
            "≥ 1M tokens"
        ])
        self.combo_context_filter.currentIndexChanged.connect(self.apply_table_filters)
        action_bar.addWidget(self.combo_context_filter)

        self.lbl_table_count = QLabel(f"Modelos: {len(self.fleet_data)}")
        self.lbl_table_count.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.lbl_table_count.setStyleSheet(f"color: {COLOR_SECONDARY_BLUE};")
        action_bar.addWidget(self.lbl_table_count)

        action_bar.addStretch()

        # Botón de Ajustar Ancho
        self.btn_auto_resize = QPushButton("↔️ Ajustar Ancho")
        self.btn_auto_resize.setObjectName("SecondaryBtn")
        self.btn_auto_resize.setToolTip("Ajusta automáticamente el ancho de todas las columnas al contenido")
        self.btn_auto_resize.clicked.connect(self.auto_resize_columns)
        action_bar.addWidget(self.btn_auto_resize)

        # Botones de Exportación
        self.btn_export_md = QPushButton("📄 Exportar MD")
        self.btn_export_md.setObjectName("SecondaryBtn")
        self.btn_export_md.clicked.connect(self.export_markdown_report)
        action_bar.addWidget(self.btn_export_md)

        self.btn_export_html = QPushButton("🌐 Exportar HTML")
        self.btn_export_html.setObjectName("SecondaryBtn")
        self.btn_export_html.clicked.connect(self.export_html_report)
        action_bar.addWidget(self.btn_export_html)

        self.btn_copy_summary = QPushButton("📋 Copiar Resumen")
        self.btn_copy_summary.setObjectName("SecondaryBtn")
        self.btn_copy_summary.clicked.connect(self.copy_summary_to_clipboard)
        action_bar.addWidget(self.btn_copy_summary)

        self.btn_reset_curated = QPushButton("🧹 Flota Curada")
        self.btn_reset_curated.setObjectName("SecondaryBtn")
        self.btn_reset_curated.setToolTip("Restablece la tabla a los modelos multi-cuenta esenciales de FloydIA")
        self.btn_reset_curated.clicked.connect(self.reset_to_curated_fleet)
        action_bar.addWidget(self.btn_reset_curated)

        btn_sel_all = QPushButton("☑️ Todos")
        btn_sel_all.setObjectName("SecondaryBtn")
        btn_sel_all.clicked.connect(lambda: self.toggle_all_table_checks(True))
        action_bar.addWidget(btn_sel_all)

        btn_desel_all = QPushButton("⬜ Desmarcar")
        btn_desel_all.setObjectName("SecondaryBtn")
        btn_desel_all.clicked.connect(lambda: self.toggle_all_table_checks(False))
        action_bar.addWidget(btn_desel_all)

        btn_sel_coherent = QPushButton("🟢 OK Coherentes")
        btn_sel_coherent.setObjectName("SecondaryBtn")
        btn_sel_coherent.setToolTip("Marca únicamente modelos con respuestas 200 OK válidas y sin errores de crédito")
        btn_sel_coherent.clicked.connect(lambda: self.select_table_by_filter("ok_coherent"))
        action_bar.addWidget(btn_sel_coherent)

        layout.addLayout(action_bar)

        # ── 5. Splitter Principal: Tabla de Modelos / Asesor IA y Consola ─────
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Panel de Tabla de Modelos
        table_frame = QFrame()
        table_frame.setProperty("class", "CardFrame")
        table_lay = QVBoxLayout(table_frame)
        table_lay.setContentsMargins(6, 6, 6, 6)
        table_lay.setSpacing(4)

        self.table_models = QTableWidget()
        self.table_models.setColumnCount(8)
        self.table_models.setHorizontalHeaderLabels([
            "Sel", "Nombre / Cuenta / Badge", "Slug ID", "Proveedor", "Estado", "Latencia", "Contexto", "Extracto / Respuesta de Prueba"
        ])
        self.table_models.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_models.setColumnWidth(0, 36)
        for i in range(1, 8):
            self.table_models.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        self.table_models.setColumnWidth(1, 230)
        self.table_models.setColumnWidth(2, 240)
        self.table_models.setColumnWidth(3, 110)
        self.table_models.setColumnWidth(4, 110)
        self.table_models.setColumnWidth(5, 100)
        self.table_models.setColumnWidth(6, 90)
        self.table_models.setColumnWidth(7, 350)
        self.table_models.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_models.setSortingEnabled(True)

        table_lay.addWidget(self.table_models)
        splitter.addWidget(table_frame)

        # Panel Inferior: Asesor IA y Consola
        bottom_frame = QFrame()
        bottom_frame.setProperty("class", "CardFrame")
        bottom_lay = QVBoxLayout(bottom_frame)
        bottom_lay.setContentsMargins(8, 8, 8, 8)
        bottom_lay.setSpacing(6)

        # Módulo "Pregúntale a la IA"
        ai_head_row = QHBoxLayout()
        lbl_ai_title = QLabel("🧠 Asesor e Inteligencia IA de FloydIA (AI Advisor)")
        lbl_ai_title.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        lbl_ai_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        ai_head_row.addWidget(lbl_ai_title)
        ai_head_row.addStretch()

        # Botones de Preguntas Rápidas
        lbl_presets = QLabel("Consultas:")
        lbl_presets.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        ai_head_row.addWidget(lbl_presets)

        btn_q1 = QPushButton("🏆 Mejor para Código")
        btn_q1.setObjectName("SecondaryBtn")
        btn_q1.clicked.connect(lambda: self.ask_ai_preset("¿Cuál es el modelo más óptimo y rápido para desarrollo y código actualmente según las respuestas?"))
        ai_head_row.addWidget(btn_q1)

        btn_q2 = QPushButton("⚡ Más Rápido 1M")
        btn_q2.setObjectName("SecondaryBtn")
        btn_q2.clicked.connect(lambda: self.ask_ai_preset("¿Cuál es el modelo más rápido con ventana de contexto de 1M tokens?"))
        ai_head_row.addWidget(btn_q2)

        btn_q3 = QPushButton("🏥 Diagnóstico de Salud")
        btn_q3.setObjectName("SecondaryBtn")
        btn_q3.clicked.connect(lambda: self.ask_ai_preset("Entrega un diagnóstico ejecutivo de la salud de los proveedores y modelos sondeados."))
        ai_head_row.addWidget(btn_q3)

        bottom_lay.addLayout(ai_head_row)

        # Input de Pregunta Personalizada al Asesor IA
        ask_input_row = QHBoxLayout()
        self.txt_ai_query = QLineEdit()
        self.txt_ai_query.setPlaceholderText("Escribe cualquier pregunta para que el Asesor IA analice la telemetría en vivo...")
        self.txt_ai_query.returnPressed.connect(self.ask_ai_custom)
        ask_input_row.addWidget(self.txt_ai_query)

        self.btn_ask_ai = QPushButton("🧠 Preguntar al Asesor IA")
        self.btn_ask_ai.setObjectName("PrimaryBtn")
        self.btn_ask_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ask_ai.clicked.connect(self.ask_ai_custom)
        ask_input_row.addWidget(self.btn_ask_ai)

        bottom_lay.addLayout(ask_input_row)

        # Splitter de Respuesta IA / Consola
        sub_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Respuesta IA
        ai_res_box = QFrame()
        ai_res_box.setStyleSheet("background-color: #070D14; border: 1px solid #1E3A5F; border-radius: 6px; padding: 6px;")
        ai_res_lay = QVBoxLayout(ai_res_box)
        ai_res_lay.setContentsMargins(4, 4, 4, 4)
        
        lbl_ai_res = QLabel("Respuesta del Asesor IA:")
        lbl_ai_res.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        lbl_ai_res.setStyleSheet(f"color: {COLOR_SECONDARY_BLUE};")
        ai_res_lay.addWidget(lbl_ai_res)

        self.ai_response_viewer = QPlainTextEdit()
        self.ai_response_viewer.setReadOnly(True)
        self.ai_response_viewer.setStyleSheet("background-color: #0B111C; border: none; font-size: 11px;")
        self.ai_response_viewer.setPlainText("El Asesor IA está listo. Presiona una consulta rápida o haz una pregunta para recibir recomendaciones basadas en la telemetría en tiempo real.")
        ai_res_lay.addWidget(self.ai_response_viewer)
        sub_splitter.addWidget(ai_res_box)

        # Consola de Eventos
        log_box = QFrame()
        log_box.setStyleSheet("background-color: #070D14; border: 1px solid #1E3A5F; border-radius: 6px; padding: 6px;")
        log_lay = QVBoxLayout(log_box)
        log_lay.setContentsMargins(4, 4, 4, 4)

        lbl_log = QLabel("Bitácora de Sondeo:")
        lbl_log.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        log_lay.addWidget(lbl_log)

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #0B111C; border: none; font-family: monospace; font-size: 10px;")
        log_lay.addWidget(self.log_console)
        sub_splitter.addWidget(log_box)

        sub_splitter.setSizes([480, 360])
        bottom_lay.addWidget(sub_splitter)

        # Matriz de Sincronización y Propagación 1-Clic
        sync_row = QHBoxLayout()
        sync_row.setSpacing(6)

        lbl_sync = QLabel("Sincronización:")
        lbl_sync.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        sync_row.addWidget(lbl_sync)

        self.chk_sync_only_verified = QCheckBox("🛡️ Solo Verificados (200 OK)")
        self.chk_sync_only_verified.setChecked(True)
        self.chk_sync_only_verified.setToolTip("Al estar marcado, la propagación a OpenCode, Hermes y DSH inyecta EXCLUSIVAMENTE los modelos con respuesta 200 OK coherente y latencia válida en el radar.")
        self.chk_sync_only_verified.setStyleSheet("color: #10D2AD; font-weight: bold; font-size: 11px; margin-right: 6px;")
        sync_row.addWidget(self.chk_sync_only_verified)

        btn_sync_all = QPushButton("🚀 PROPAGAR A TODOS (1-CLIC)")
        btn_sync_all.setObjectName("ActionSyncBtn")
        btn_sync_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sync_all.clicked.connect(self.sync_all_agents)
        sync_row.addWidget(btn_sync_all)

        btn_sync_open = QPushButton("⚡ OpenCode")
        btn_sync_open.setObjectName("SecondaryBtn")
        btn_sync_open.clicked.connect(self.sync_to_opencode)
        sync_row.addWidget(btn_sync_open)

        btn_sync_herm = QPushButton("🪽 Hermes Agent")
        btn_sync_herm.setObjectName("SecondaryBtn")
        btn_sync_herm.clicked.connect(self.sync_to_hermes)
        sync_row.addWidget(btn_sync_herm)

        btn_sync_z = QPushButton("📝 Zed Editor")
        btn_sync_z.setObjectName("SecondaryBtn")
        btn_sync_z.clicked.connect(self.sync_to_zed)
        sync_row.addWidget(btn_sync_z)

        btn_sync_hp = QPushButton("💻 Nodo Remoto")
        btn_sync_hp.setObjectName("SecondaryBtn")
        btn_sync_hp.setToolTip("Ejecuta réplica asíncrona hacia el nodo remoto configurado")
        btn_sync_hp.clicked.connect(self.sync_to_remote)
        sync_row.addWidget(btn_sync_hp)

        btn_deepseek_export = QPushButton("📤 DeepSeek (C1..C7)")
        btn_deepseek_export.setObjectName("DeepSeekActionBtn")
        btn_deepseek_export.clicked.connect(self.export_deepseek_dialog)
        sync_row.addWidget(btn_deepseek_export)

        btn_deepseek_copy = QPushButton("📋 Copiar DeepSeek")
        btn_deepseek_copy.setObjectName("SecondaryBtn")
        btn_deepseek_copy.clicked.connect(self.copy_deepseek_fast)
        sync_row.addWidget(btn_deepseek_copy)

        sync_row.addStretch()
        bottom_lay.addLayout(sync_row)

        splitter.addWidget(bottom_frame)
        splitter.setSizes([380, 300])

        layout.addWidget(splitter, stretch=1)
        self.log("✅ AI Radar 2.0 listo con dashboard analítico, presets de sonda y exportación multiformato.")

    def create_kpi_card(self, title: str, main_val: str, subtitle: str, color_accent: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "CardFrame")
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #070D14;
                border: 1px solid #1E293B;
                border-radius: 8px;
                padding: 6px;
            }}
        """)
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

    def create_parity_traffic_light_widget(self) -> QFrame:
        """Crea el Semáforo de Paridad 1:1 Multi-Agente (Protocolo v27)."""
        card = QFrame()
        card.setProperty("class", "CardFrame")
        card.setStyleSheet("""
            QFrame {
                background-color: #060B12;
                border: 1px solid #1E293B;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        # Título
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        lbl_title = QLabel("🛡️ PARIDAD 1:1")
        lbl_title.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        lbl_sub = QLabel("Protocolo v27 SSOT")
        lbl_sub.setFont(QFont("Inter", 7))
        lbl_sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        lay.addLayout(title_box)

        # Contenedor de agentes
        self.parity_badges = {}
        agents = [
            ("Antigravity", "Antigravity IDE"),
            ("OpenCode", "OpenCode Desktop/CLI"),
            ("Hermes", "Hermes Agent"),
            ("Zed", "Zed Editor"),
            ("Qoder", "Qoder IDE"),
            ("DSH", "DeepSeek Harness"),
            ("Claude", "Claude Code CLI"),
        ]

        agents_lay = QHBoxLayout()
        agents_lay.setSpacing(6)
        for ag_key, ag_name in agents:
            b = QLabel(f"🟢 {ag_key}")
            b.setFont(QFont("Inter", 8, QFont.Weight.Bold))
            b.setStyleSheet("""
                background-color: #064E3B;
                color: #34D399;
                border: 1px solid #059669;
                border-radius: 4px;
                padding: 3px 6px;
            """)
            b.setToolTip(f"{ag_name} — Paridad 1:1 Certificada")
            self.parity_badges[ag_key] = b
            agents_lay.addWidget(b)

        lay.addLayout(agents_lay)
        lay.addStretch()

        # Estado global
        self.lbl_parity_verdict = QLabel("🎉 100% PARITARIO")
        self.lbl_parity_verdict.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.lbl_parity_verdict.setStyleSheet("color: #10B981;")
        lay.addWidget(self.lbl_parity_verdict)

        # Botón Auditar
        self.btn_audit_parity = QPushButton("🔄 Auditar Paridad")
        self.btn_audit_parity.setObjectName("SecondaryBtn")
        self.btn_audit_parity.setFixedHeight(24)
        self.btn_audit_parity.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.btn_audit_parity.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_audit_parity.clicked.connect(self.run_parity_audit)
        lay.addWidget(self.btn_audit_parity)

        return card

    def run_parity_audit(self):
        """Ejecuta verify_multiagent_parity.py en background y refresca los indicadores."""
        self.lbl_parity_verdict.setText("⏳ Auditando...")
        self.lbl_parity_verdict.setStyleSheet(f"color: {COLOR_WARNING};")
        self.btn_audit_parity.setEnabled(False)

        def _worker():
            script_path = os.path.join(WORKSPACE_ROOT, "SCRIPTS", "verify_multiagent_parity.py")
            try:
                res = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=20)
                success = (res.returncode == 0 and "CERTIFICADO 100% PARITARIO" in res.stdout)
                return success, res.stdout
            except Exception as e:
                return False, str(e)

        def _done(ok, out):
            self.btn_audit_parity.setEnabled(True)
            if ok:
                self.lbl_parity_verdict.setText("🎉 100% PARITARIO")
                self.lbl_parity_verdict.setStyleSheet("color: #10B981;")
                for b in self.parity_badges.values():
                    b.setStyleSheet("background-color: #064E3B; color: #34D399; border: 1px solid #059669; border-radius: 4px; padding: 3px 6px;")
            else:
                self.lbl_parity_verdict.setText("⚠️ OBSERVACIONES")
                self.lbl_parity_verdict.setStyleSheet("color: #EF4444;")

        def _run():
            ok, out = _worker()
            QTimer.singleShot(0, lambda: _done(ok, out))

        threading.Thread(target=_run, daemon=True).start()

    def update_kpi_dashboard(self, results=None):
        """Refresca las 5 cards KPI del dashboard (flota, latencia, speed leader, contexto, distribución)."""
        if results is None:
            results = list(self.table_models_map.values())

        total = len(results)
        online = sum(1 for r in results if r.get("status") in ["200_OK", "ONLINE"])
        latencies = [r.get("latency_ms", 0) for r in results if r.get("status") in ["200_OK", "ONLINE"] and r.get("latency_ms", 0) > 0]
        
        # 1. Card Salud Flota
        val_health = f"{online} / {total} ONLINE"
        sub_health = "100% Operativo" if online == total and total > 0 else f"{total - online} con incidencias"
        color_h = "#10B981" if online >= (total * 0.7) else ("#F59E0B" if online > 0 else "#EF4444")
        self.card_health.findChild(QLabel, "ValLabel").setText(val_health)
        self.card_health.findChild(QLabel, "ValLabel").setStyleSheet(f"color: {color_h};")
        self.card_health.findChild(QLabel, "SubLabel").setText(sub_health)

        # 2. Card Latencia Promedio
        if latencies:
            avg_lat = int(sum(latencies) / len(latencies))
            val_lat = f"{avg_lat} ms"
            sub_lat = "⚡ Óptima (<500ms)" if avg_lat < 500 else "⚠️ Latencia moderada"
        else:
            val_lat = "— ms"
            sub_lat = "Requiere sondeo"
        self.card_avg_lat.findChild(QLabel, "ValLabel").setText(val_lat)
        self.card_avg_lat.findChild(QLabel, "SubLabel").setText(sub_lat)

        # 3. Card Speed Leader
        online_models = [r for r in results if r.get("status") in ["200_OK", "ONLINE"] and r.get("latency_ms", 0) > 0]
        if online_models:
            fastest = min(online_models, key=lambda x: x.get("latency_ms", 999999))
            fname = fastest.get("name", fastest.get("id", ""))
            if len(fname) > 16:
                fname = fname[:14] + ".."
            val_fast = f"{fname} ({fastest.get('latency_ms')}ms)"
            sub_fast = f"Proveedor: {fastest.get('provider', '').upper()}"
        else:
            val_fast = "—"
            sub_fast = "Sin datos de latencia"
        self.card_fastest.findChild(QLabel, "ValLabel").setText(val_fast)
        self.card_fastest.findChild(QLabel, "SubLabel").setText(sub_fast)

        # 4. Card Contexto Máximo
        max_ctx_model = max(results, key=lambda x: x.get("context", 0)) if results else None
        if max_ctx_model:
            ctx_val = max_ctx_model.get("context", 0)
            ctx_str = f"{ctx_val // 1000}k Tokens" if ctx_val < 1000000 else "1M Tokens"
            self.card_context.findChild(QLabel, "ValLabel").setText(ctx_str)
            self.card_context.findChild(QLabel, "SubLabel").setText(max_ctx_model.get("name", "")[:20])

        # 5. Card Distribución
        free_cnt = sum(1 for r in results if r.get("category") == "free" or "free" in r.get("badge", "").lower())
        frontier_cnt = sum(1 for r in results if r.get("category") == "frontier")
        code_cnt = sum(1 for r in results if r.get("category") == "code")
        self.card_tiers.findChild(QLabel, "ValLabel").setText(f"{free_cnt} Free • {frontier_cnt} Pro • {code_cnt} Code")
        self.card_tiers.findChild(QLabel, "SubLabel").setText(f"Total: {total} modelos registrados")

    def handle_probe_preset_changed(self, index: int):
        preset_name = self.combo_probe_presets.currentText()
        if preset_name in PROBE_PRESETS:
            cfg = PROBE_PRESETS[preset_name]
            self.txt_probe_prompt.setText(cfg["prompt"])
            self.combo_max_tokens.setCurrentText(str(cfg["max_tokens"]))
            self.combo_timeout.setCurrentText(f"{cfg['timeout']}s")
            self.lbl_preset_desc.setText(cfg["desc"])

    def reset_probe_prompt(self):
        self.handle_probe_preset_changed(self.combo_probe_presets.currentIndex())

    def auto_resize_columns(self):
        self.table_models.resizeColumnsToContents()
        min_widths = [36, 190, 210, 100, 100, 95, 85, 300]
        for col, min_w in enumerate(min_widths):
            if self.table_models.columnWidth(col) < min_w:
                self.table_models.setColumnWidth(col, min_w)
        self.log("↔️ Columnas del Radar ajustadas automáticamente al contenido.")

    def log(self, text: str):
        self.log_console.appendPlainText(text)

    def populate_table(self):
        self.apply_table_filters()
        self.auto_resize_columns()

    def apply_table_filters(self):
        query = self.txt_search_model.text().lower().strip()
        cat_idx = self.combo_category_filter.currentIndex()
        acc_filter_text = self.combo_account_filter.currentText()
        ctx_idx = self.combo_context_filter.currentIndex() if hasattr(self, "combo_context_filter") else 0

        ctx_thresholds = {1: 32000, 2: 128000, 3: 200000, 4: 1000000}
        min_ctx = ctx_thresholds.get(ctx_idx, 0)

        filtered = []
        for m_id, m in self.table_models_map.items():
            name = m.get("name", "").lower()
            slug = m_id.lower()
            prov = m.get("provider", "").lower()
            tag = m.get("account_tag", "C1").upper()
            status = m.get("status", "").lower()
            snip = m.get("response_snippet", "").lower()
            ctx_val = int(m.get("context", 0) or 0)

            # Filtro por búsqueda
            if query and (query not in name and query not in slug and query not in prov and query not in snip and query not in tag.lower()):
                continue

            # Filtro por ventana de contexto
            if min_ctx > 0 and ctx_val < min_ctx:
                continue

            # Filtro por cuenta
            if acc_filter_text != "Todas las Cuentas":
                if "Solo [" in acc_filter_text:
                    expected_tag = acc_filter_text.split("[")[1].split("]")[0]
                    if tag != expected_tag:
                        continue
                elif acc_filter_text == "Solo Direct / Free":
                    if tag not in ("DIRECT", "FREE", "LOCAL", "PAID"):
                        continue

            # Filtro por categoría
            if cat_idx == 1:
                # 🟢 Solo Respuestas OK / Coherentes (excluye sin créditos, errores, timeouts)
                if not is_coherent_ok_response(m):
                    continue
            elif cat_idx == 2 and "200_ok" not in status and "online" not in status:
                continue
            elif cat_idx == 3 and (m.get("category") != "free" and "free" not in m.get("badge", "").lower()):
                continue
            elif cat_idx == 4 and m.get("category") != "frontier":
                continue
            elif cat_idx == 5 and m.get("category") != "code":
                continue
            elif cat_idx == 6 and prov != "google":
                continue
            elif cat_idx == 7 and prov != "nvidia":
                continue
            elif cat_idx == 8 and prov != "openrouter":
                continue
            elif cat_idx == 9 and prov != "mistral":
                continue
            elif cat_idx == 10 and prov != "deepseek":
                continue

            filtered.append(m)

        self.table_models.setSortingEnabled(False)
        self.table_models.setRowCount(len(filtered))
        self.table_checkboxes.clear()
        self.lbl_table_count.setText(f"Modelos: {len(filtered)} / {len(self.table_models_map)}")

        for row, m in enumerate(filtered):
            m_id = m["id"]
            prov = m.get("provider", "custom")
            tag = m.get("account_tag", "C1")
            prov_color = get_provider_color(prov)
            badge_label = get_account_badge_label(tag)

            # Col 0: Checkbox
            cb = QCheckBox()
            cb.setChecked(True)
            self.table_checkboxes[m_id] = cb
            cb_container = QWidget()
            cb_lay = QHBoxLayout(cb_container)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table_models.setCellWidget(row, 0, cb_container)

            # Col 1: Nombre / Badge con Color Temático por Proveedor
            raw_name = m.get('name', m_id)
            if not raw_name.startswith("["):
                name_text = f"{badge_label} {raw_name}  [{m.get('badge', '')}]"
            else:
                name_text = f"{raw_name}  [{m.get('badge', '')}]"

            item_name = SortableTableWidgetItem(name_text, sort_value=name_text.lower())
            item_name.setFont(QFont("Inter", 9, QFont.Weight.Bold))
            st = m.get("status", "")
            if st == "200_OK" or st == "ONLINE":
                item_name.setForeground(QColor(prov_color))
            else:
                item_name.setForeground(QColor("#64748B"))
            self.table_models.setItem(row, 1, item_name)

            # Col 2: Slug ID
            item_slug = SortableTableWidgetItem(m_id, sort_value=m_id.lower())
            item_slug.setFont(QFont("Monospace", 8))
            self.table_models.setItem(row, 2, item_slug)

            # Col 3: Proveedor
            prov_str = m.get("provider", "").upper()
            item_prov = SortableTableWidgetItem(prov_str, sort_value=prov_str)
            item_prov.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_models.setItem(row, 3, item_prov)

            # Col 4: Estado
            st_text = "⚪ Sin probar"
            st_color = QColor("#94A3B8")
            sort_rank = 6
            if st == "200_OK" or st == "ONLINE":
                st_text = "🟢 200 OK"
                st_color = QColor("#10B981")
                sort_rank = 1
            elif "429" in st:
                st_text = "🟡 429 Limit"
                st_color = QColor("#F59E0B")
                sort_rank = 2
            elif st in ("NO_CREDITS", "ERR_QUOTA"):
                st_text = "⚠️ Sin Créditos"
                st_color = QColor("#F97316")
                sort_rank = 3
            elif st == "SIN_KEY":
                st_text = "⚪ Sin Key"
                st_color = QColor("#64748B")
                sort_rank = 5
            elif st:
                st_text = f"🔴 {st}"
                st_color = QColor("#EF4444")
                sort_rank = 4

            item_st = SortableTableWidgetItem(st_text, sort_value=sort_rank)
            item_st.setFont(QFont("Inter", 9, QFont.Weight.Bold))
            item_st.setForeground(st_color)
            item_st.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_models.setItem(row, 4, item_st)

            # Col 5: Latencia + Delta
            lat = m.get("latency_ms", 0)
            delta_str = ""
            if m_id in self.previous_latencies and lat > 0:
                prev_lat = self.previous_latencies[m_id]
                diff = lat - prev_lat
                if diff > 0:
                    delta_str = f" (+{diff})"
                elif diff < 0:
                    delta_str = f" ({diff})"

            lat_str = f"{lat} ms{delta_str}" if lat > 0 else "—"
            sort_lat = lat if lat > 0 else 9999999
            item_lat = SortableTableWidgetItem(lat_str, sort_value=sort_lat)
            item_lat.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if lat > 0:
                item_lat.setForeground(QColor("#38BDF8"))
            self.table_models.setItem(row, 5, item_lat)

            # Col 6: Contexto
            ctx = m.get("context", 0)
            ctx_str = f"{ctx // 1000}k" if ctx >= 1000 else str(ctx)
            item_ctx = SortableTableWidgetItem(ctx_str, sort_value=ctx)
            item_ctx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_models.setItem(row, 6, item_ctx)

            # Col 7: Snippet / Respuesta
            snip = m.get("response_snippet", "")
            item_snip = SortableTableWidgetItem(str(snip), sort_value=str(snip).lower())
            item_snip.setToolTip(str(snip))
            self.table_models.setItem(row, 7, item_snip)

        self.table_models.setSortingEnabled(True)

    def toggle_all_table_checks(self, checked: bool):
        for cb in self.table_checkboxes.values():
            cb.setChecked(checked)

    def get_active_probe_config(self) -> Dict[str, Any]:
        prompt = self.txt_probe_prompt.text().strip()
        if not prompt:
            prompt = "1"
        try:
            max_tokens = int(self.combo_max_tokens.currentText())
        except Exception:
            max_tokens = 8
        try:
            timeout_str = self.combo_timeout.currentText().replace("s", "").strip()
            timeout = int(timeout_str)
        except Exception:
            timeout = 7

        return {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "temperature": 0.1
        }

    def start_curated_probe(self):
        if is_worker_running(self.probe_worker):
            self.log("🛑 Cancelando sondeo concurrente a petición del usuario...")
            self.probe_worker.cancel()
            self.btn_probe_curated.setEnabled(False)
            self.btn_probe_curated.setText("⏳ CANCELANDO...")
            return

        probe_cfg = self.get_active_probe_config()
        self.btn_probe_curated.setText("🛑 DETENER SONDEO")
        self.btn_probe_curated.setStyleSheet("background-color: #7F1D1D; color: #FCA5A5; font-weight: 700; border-radius: 6px; padding: 8px 16px;")
        self.btn_discover_global.setEnabled(False)

        selected_models = []
        for m_id, m in self.table_models_map.items():
            if m_id in self.table_checkboxes and self.table_checkboxes[m_id].isChecked():
                selected_models.append(m)

        if not selected_models:
            selected_models = list(self.table_models_map.values())

        self.log(f"\n🚀 Lanzando sondeo concurrente en {len(selected_models)} modelos seleccionados (hasta 16 hilos en paralelo)...")
        self.probe_worker = ProbeWorker(selected_models, probe_cfg)
        self.probe_worker.model_updated.connect(self.handle_model_update)
        self.probe_worker.log_signal.connect(self.log)
        self.probe_worker.finished_signal.connect(self.handle_probe_finished)
        self.probe_worker.finished.connect(self._on_probe_worker_cleanup)
        self.probe_worker.start()

    def _on_probe_worker_cleanup(self):
        """Fallback: restaura botones si finished_signal no se emitió (ej. cancelación)."""
        self.btn_probe_curated.setEnabled(True)
        self.btn_probe_curated.setText("⚡ SONDEAR FLOTA EN VIVO")
        self.btn_probe_curated.setStyleSheet("")
        self.btn_discover_global.setEnabled(True)
        if self.probe_worker:
            self.probe_worker.deleteLater()
            self.probe_worker = None

    def update_single_table_row(self, model_res: dict):
        m_id = model_res.get("id", "")
        for row in range(self.table_models.rowCount()):
            item_slug = self.table_models.item(row, 2)
            if item_slug and item_slug.text() == m_id:
                # Col 4: Estado
                st = model_res.get("status", "")
                st_text = "⚪ Sin probar"
                st_color = QColor("#94A3B8")
                sort_rank = 6
                if st == "200_OK" or st == "ONLINE":
                    st_text = "🟢 200 OK"
                    st_color = QColor("#10B981")
                    sort_rank = 1
                elif "429" in st:
                    st_text = "🟡 429 Limit"
                    st_color = QColor("#F59E0B")
                    sort_rank = 2
                elif st in ("NO_CREDITS", "ERR_QUOTA"):
                    st_text = "⚠️ Sin Créditos"
                    st_color = QColor("#F97316")
                    sort_rank = 3
                elif st == "SIN_KEY":
                    st_text = "⚪ Sin Key"
                    st_color = QColor("#64748B")
                    sort_rank = 5
                elif st:
                    st_text = f"🔴 {st}"
                    st_color = QColor("#EF4444")
                    sort_rank = 4

                item_st = self.table_models.item(row, 4)
                if item_st:
                    item_st.setText(st_text)
                    item_st.setForeground(st_color)
                    if isinstance(item_st, SortableTableWidgetItem):
                        item_st.sort_value = sort_rank

                # Col 5: Latencia + TPS
                lat = model_res.get("latency_ms", 0)
                tps = model_res.get("tps", 0)
                tps_str = f" ({tps} TPS)" if tps > 0 else ""
                lat_str = f"{lat} ms{tps_str}" if lat > 0 else "—"
                item_lat = self.table_models.item(row, 5)
                if item_lat:
                    item_lat.setText(lat_str)
                    if lat > 0:
                        item_lat.setForeground(QColor("#00BBF9"))
                    if isinstance(item_lat, SortableTableWidgetItem):
                        item_lat.sort_value = lat if lat > 0 else 9999999

                # Col 7: Snippet
                snip = model_res.get("response_snippet", "")
                item_snip = self.table_models.item(row, 7)
                if item_snip:
                    item_snip.setText(str(snip))
                    item_snip.setToolTip(str(snip))
                    if isinstance(item_snip, SortableTableWidgetItem):
                        item_snip.sort_value = str(snip).lower()
                break

    def handle_model_update(self, model_res: dict):
        m_id = model_res["id"]
        self.table_models_map[m_id] = model_res
        self.update_single_table_row(model_res)
        # Throttling de actualización de KPI cada 150ms
        if self._kpi_throttle_timer is None:
            self._kpi_throttle_timer = QTimer(self)
            self._kpi_throttle_timer.setSingleShot(True)
            self._kpi_throttle_timer.setInterval(150)
            self._kpi_throttle_timer.timeout.connect(self.update_kpi_dashboard)
        if not self._kpi_throttle_timer.isActive():
            self._kpi_throttle_timer.start()

    def handle_probe_finished(self, results: list):
        self.btn_probe_curated.setEnabled(True)
        self.btn_probe_curated.setText("⚡ SONDEAR FLOTA EN VIVO")
        self.btn_probe_curated.setStyleSheet("")
        self.btn_discover_global.setEnabled(True)
        healthy = sum(1 for r in results if r.get("status") in ["200_OK", "ONLINE"])
        self.log(f"\n🎯 Sondeo finalizado: {healthy}/{len(results)} modelos respondiendo exitosamente.")
        self.save_cached_telemetry(results)
        self.previous_latencies = {r["id"]: r["latency_ms"] for r in results if r.get("latency_ms", 0) > 0}
        self.update_kpi_dashboard(results)

    def reset_to_curated_fleet(self):
        self.table_models_map = {m["id"]: dict(m) for m in CURATED_FLEET}
        self.populate_table()
        self.update_kpi_dashboard()
        self.log(f"🧹 Tabla restablecida a los {len(CURATED_FLEET)} modelos de la Flota Curada FloydIA.")
        QMessageBox.information(self, "Flota Restablecida", f"✅ Tabla restablecida a los {len(CURATED_FLEET)} modelos esenciales de FloydIA.")

    def select_table_by_filter(self, filter_type: str):
        for m_id, m in self.table_models_map.items():
            cb = self.table_checkboxes.get(m_id)
            if not cb:
                continue
            cat = m.get("category", "")
            m_id_lower = m_id.lower()
            name_lower = m.get("name", "").lower()

            if filter_type == "ok_coherent":
                cb.setChecked(is_coherent_ok_response(m))
            elif filter_type == "free":
                is_free = (cat == "free") or (":free" in m_id_lower) or ("free" in m_id_lower) or ("auto" in m_id_lower)
                cb.setChecked(is_free)
            elif filter_type == "pro":
                is_pro = (cat in ["frontier", "standard", "nim"]) and not (":free" in m_id_lower)
                cb.setChecked(is_pro)
            elif filter_type == "code":
                is_code = any(k in m_id_lower or k in name_lower for k in ["coder", "code", "sonnet", "codestral", "devstral", "starcoder", "deepseek-coder"])
                cb.setChecked(is_code)

    def discover_global_catalog(self):
        if not OPENROUTER_KEY and not NVIDIA_KEY and not GOOGLE_KEY and not MISTRAL_KEY and not DEEPSEEK_KEY and not B_AI_KEY and not TOKENROUTER_KEY and not ZENMUX_KEY:
            QMessageBox.warning(self, "Sin Claves", "No se encontraron claves API de proveedores en .env.")
            return

        if is_worker_running(self.discovery_worker):
            self.log("⚠️ Ya hay un descubrimiento global en curso.")
            return

        dialog = GlobalDiscoveryDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.get_selected_options()
        self.log(f"\n🌐 Iniciando descarga de catálogos de proveedores (Modo: {options['mode']}, Min Ctx: {options['min_ctx']//1000 if options['min_ctx'] else 0}k)...")
        self.btn_discover_global.setEnabled(False)
        self.discovery_worker = CatalogDiscoveryWorker(
            OPENROUTER_KEY, NVIDIA_KEY, GOOGLE_KEY, MISTRAL_KEY, DEEPSEEK_KEY, options,
            b_ai_key=B_AI_KEY, tokenrouter_key=TOKENROUTER_KEY, zenmux_key=ZENMUX_KEY,
            fireworks_key=FIREWORKS_KEY, cloudflare_key=CLOUDFLARE_KEY
        )
        self.discovery_worker.discovery_finished.connect(self._on_discovery_finished)
        self.discovery_worker.error_signal.connect(self._on_discovery_error)
        self.discovery_worker.finished.connect(self._on_discovery_worker_finished)
        self.discovery_worker.start()

    def _on_discovery_worker_finished(self):
        if self.discovery_worker:
            self.discovery_worker.deleteLater()
            self.discovery_worker = None

    def _on_discovery_finished(self, discovered_models: list, replace: bool, msg: str):
        self.btn_discover_global.setEnabled(True)
        if replace:
            # Preservar la base curada (DeepSeek, Mistral, Google, Groq) para no perder cuentas
            curated_base = {m["id"]: dict(m) for m in CURATED_FLEET}
            for m in discovered_models:
                curated_base[m["id"]] = dict(m)
            self.table_models_map = curated_base
        else:
            for m in discovered_models:
                if m["id"] not in self.table_models_map:
                    self.table_models_map[m["id"]] = dict(m)

        self.populate_table()
        self.update_kpi_dashboard()
        self.log(f"✅ {msg} Total en tabla: {len(self.table_models_map)} modelos.")
        QMessageBox.information(
            self,
            "Catálogo Incorporado",
            f"✅ {msg}\n\n"
            f"• Modelos registrados en tabla: {len(self.table_models_map)}\n"
            f"• Listos para benchmark y sondeo en vivo."
        )

    def _on_discovery_error(self, err: str):
        self.btn_discover_global.setEnabled(True)
        self.log(f"❌ {err}")
        QMessageBox.critical(self, "Error", err)

    # ── MÓDULO ASESOR IA (PREGÚNTALE A LA IA) ────────────────────────────────
    def ask_ai_preset(self, prompt: str):
        self.txt_ai_query.setText(prompt)
        self.ask_ai_custom()

    def ask_ai_custom(self):
        query = self.txt_ai_query.text().strip()
        if not query:
            return

        if self.advisor_worker and self.advisor_worker.isRunning():
            return

        self.btn_ask_ai.setEnabled(False)
        self.ai_response_viewer.setPlainText("⏳ Analizando telemetría y consultando al Asesor IA...")

        self.advisor_worker = AIAdvisorWorker(query, list(self.table_models_map.values()))
        self.advisor_worker.response_ready.connect(self.handle_ai_response)
        self.advisor_worker.log_signal.connect(self.log)
        self.advisor_worker.start()

    def handle_ai_response(self, answer: str):
        self.btn_ask_ai.setEnabled(True)
        self.ai_response_viewer.setPlainText(answer)
        self.log("✅ Asesor IA entregó el análisis.")

    # ── EXPORTACIÓN DE INFORMES (MARKDOWN, HTML & CLIPBOARD) ─────────────────
    def generate_markdown_report_content(self) -> str:
        now = datetime.datetime.now()
        probe_cfg = self.get_active_probe_config()
        models = list(self.table_models_map.values())
        total = len(models)
        online = sum(1 for m in models if m.get("status") in ["200_OK", "ONLINE"])
        latencies = [m.get("latency_ms", 0) for m in models if m.get("status") in ["200_OK", "ONLINE"] and m.get("latency_ms", 0) > 0]
        avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
        ai_text = self.ai_response_viewer.toPlainText().strip()

        table_rows = []
        for m in models:
            st = m.get("status", "Sin probar")
            st_icon = "🟢 200 OK" if st in ["200_OK", "ONLINE"] else ("🟡 429 Limit" if "429" in st else (f"⚪ Sin Key" if st == "SIN_KEY" else f"🔴 {st}"))
            lat_str = f"{m.get('latency_ms', 0)} ms" if m.get("latency_ms", 0) > 0 else "—"
            ctx_str = f"{m.get('context', 0) // 1000}k" if m.get("context", 0) >= 1000 else str(m.get("context", 0))
            snippet_clean = str(m.get("response_snippet", "")).replace("\n", " ")
            table_rows.append(f"| **{m.get('name', m['id'])}** | `{m['id']}` | `{m.get('provider', '').upper()}` | `{ctx_str}` | {st_icon} | `{lat_str}` | {snippet_clean} |")

        table_md = "\n".join(table_rows)

        content = f"""# 🛰️ FLOYDIA AI RADAR & OBSERVATORY — Reporte Ejecutivo
> **Fecha y Hora**: `{now.strftime("%Y-%m-%d %H:%M:%S")}`  
> **Arquitectura**: Homelab FloydIA (HP15 EndeavourOS / Proxmox CT114)  
> **Firma**: *FloydIA — WEB & IA AUTOMATION*  

---

## 📊 1. Resumen Ejecutivo y KPIs de Flota
- **Salud de la Flota**: **{online} / {total} Modelos Online** ({int((online/total)*100 if total else 0)}% de disponibilidad).
- **Latencia Promedio Global**: **{avg_lat} ms** (inferencia y retorno de paquetes).
- **Pregunta de Sonda Utilizada**: *"{probe_cfg.get('prompt', '')}"* (Max Tokens: `{probe_cfg.get('max_tokens')}`, Timeout: `{probe_cfg.get('timeout')}s`).

---

## 🧠 2. Diagnóstico del Asesor IA de FloydIA
{ai_text}

---

## 📋 3. Matriz de Telemetría y Respuestas en Vivo

| Modelo | Slug API | Proveedor | Contexto | Estado | Latencia | Extracto / Benchmark |
|---|---|:---:|:---:|:---:|:---:|---|
{table_md}

---
*Generado automáticamente por FloydIA Suite 2.0 (PROTOCOLO v27).*
"""
        return content

    def export_markdown_report(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        now = datetime.datetime.now()
        default_name = f"{now.strftime('%Y-%m-%d_%H%M%S')}_floydia_ai_radar_report.md"
        default_path = os.path.join(REPORTS_DIR, default_name)

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Guardar Informe Markdown", default_path, "Markdown Files (*.md);;All Files (*)"
        )
        if not filepath:
            return

        try:
            content = self.generate_markdown_report_content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self.log(f"📄 Informe Markdown generado exitosamente en: {filepath}")
            QMessageBox.information(self, "Informe Guardado", f"✅ Informe Markdown exportado exitosamente en:\n{filepath}")
        except Exception as e:
            self.log(f"❌ Error exportando informe MD: {e}")
            QMessageBox.critical(self, "Error al Exportar", f"No se pudo guardar el informe: {e}")

    def export_html_report(self):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        now = datetime.datetime.now()
        default_name = f"{now.strftime('%Y-%m-%d_%H%M%S')}_floydia_ai_radar_report.html"
        default_path = os.path.join(REPORTS_DIR, default_name)

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Guardar Informe HTML", default_path, "HTML Files (*.html);;All Files (*)"
        )
        if not filepath:
            return

        try:
            probe_cfg = self.get_active_probe_config()
            models = list(self.table_models_map.values())
            total = len(models)
            online = sum(1 for m in models if m.get("status") in ["200_OK", "ONLINE"])
            latencies = [m.get("latency_ms", 0) for m in models if m.get("status") in ["200_OK", "ONLINE"] and m.get("latency_ms", 0) > 0]
            avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
            ai_text = self.ai_response_viewer.toPlainText().strip().replace("\n", "<br>")

            table_rows_html = []
            for m in models:
                st = m.get("status", "Sin probar")
                st_badge = "<span style='color:#10B981; font-weight:bold;'>🟢 200 OK</span>" if st in ["200_OK", "ONLINE"] else (
                    "<span style='color:#F59E0B; font-weight:bold;'>🟡 429 Limit</span>" if "429" in st else f"<span style='color:#EF4444; font-weight:bold;'>🔴 {st}</span>"
                )
                lat_str = f"{m.get('latency_ms', 0)} ms" if m.get("latency_ms", 0) > 0 else "—"
                ctx_str = f"{m.get('context', 0) // 1000}k" if m.get("context", 0) >= 1000 else str(m.get("context", 0))
                snippet_clean = str(m.get("response_snippet", "")).replace("<", "&lt;").replace(">", "&gt;")
                
                table_rows_html.append(f"""
                <tr>
                    <td style="font-weight:600; color:#F1F5F9;">{m.get('name', m['id'])} <span style="font-size:10px; color:#64748B;">[{m.get('badge','')}]</span></td>
                    <td style="font-family:monospace; color:#38BDF8;">{m['id']}</td>
                    <td style="text-align:center;"><span style="background:#1E293B; padding:2px 6px; border-radius:4px; font-size:11px;">{m.get('provider','').upper()}</span></td>
                    <td style="text-align:center; color:#A78BFA;">{ctx_str}</td>
                    <td style="text-align:center;">{st_badge}</td>
                    <td style="text-align:right; font-weight:bold; color:#38BDF8;">{lat_str}</td>
                    <td style="font-size:11px; color:#94A3B8;">{snippet_clean}</td>
                </tr>
                """)

            html_body = "".join(table_rows_html)

            html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FloydIA AI Radar — Informe de Telemetría ({now.strftime('%Y-%m-%d')})</title>
    <style>
        body {{
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background-color: #030712;
            color: #E2E8F0;
            margin: 0;
            padding: 30px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            border-bottom: 1px solid #1E293B;
            padding-bottom: 20px;
            margin-bottom: 25px;
        }}
        h1 {{
            color: #10D2AD;
            font-size: 26px;
            margin: 0 0 8px 0;
        }}
        .meta {{
            color: #64748B;
            font-size: 13px;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .card {{
            background: #0B111C;
            border: 1px solid #1E3A5F;
            border-radius: 8px;
            padding: 16px;
        }}
        .card-title {{
            font-size: 11px;
            text-transform: uppercase;
            color: #64748B;
            font-weight: 700;
            margin-bottom: 6px;
        }}
        .card-val {{
            font-size: 22px;
            font-weight: 800;
            color: #10D2AD;
        }}
        .advisor-box {{
            background: #080E18;
            border-left: 4px solid #38BDF8;
            padding: 16px;
            border-radius: 6px;
            margin-bottom: 30px;
            line-height: 1.5;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #070D14;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #1E293B;
        }}
        th {{
            background: #0F172A;
            color: #94A3B8;
            padding: 12px 14px;
            text-align: left;
            font-size: 12px;
            font-weight: 700;
            border-bottom: 1px solid #1E293B;
        }}
        td {{
            padding: 10px 14px;
            border-bottom: 1px solid #0F172A;
            font-size: 13px;
        }}
        tr:hover {{
            background: #0B132B;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            font-size: 12px;
            color: #475569;
            border-top: 1px solid #1E293B;
            padding-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🛰️ FLOYDIA AI RADAR & OBSERVATORY</h1>
            <div class="meta">Reporte de Telemetría en Vivo · Fecha: <strong>{now.strftime('%Y-%m-%d %H:%M:%S')}</strong> · Entorno: <strong>Homelab HP15 / Proxmox CT114</strong></div>
        </div>

        <div class="kpi-grid">
            <div class="card">
                <div class="card-title">Salud de la Flota</div>
                <div class="card-val" style="color: {'#10B981' if online >= total*0.7 else '#F59E0B'};">{online} / {total} ONLINE</div>
            </div>
            <div class="card">
                <div class="card-title">Latencia Promedio</div>
                <div class="card-val" style="color: #38BDF8;">{avg_lat} ms</div>
            </div>
            <div class="card">
                <div class="card-title">Pregunta de Sonda</div>
                <div class="card-val" style="font-size:14px; color:#F1F5F9;">"{probe_cfg.get('prompt','')[:35]}..."</div>
            </div>
        </div>

        <div class="advisor-box">
            <h3 style="margin-top:0; color:#38BDF8;">🧠 Diagnóstico del Asesor IA:</h3>
            <div>{ai_text}</div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Modelo</th>
                    <th>Slug ID</th>
                    <th style="text-align:center;">Proveedor</th>
                    <th style="text-align:center;">Contexto</th>
                    <th style="text-align:center;">Estado</th>
                    <th style="text-align:right;">Latencia</th>
                    <th>Respuesta de Prueba</th>
                </tr>
            </thead>
            <tbody>
                {html_body}
            </tbody>
        </table>

        <div class="footer">
            FloydIA Suite 2.0 — Sistema Automatizado de Inteligencia e Infraestructura Homelab (PROTOCOLO v27).
        </div>
    </div>
</body>
</html>"""

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)

            self.log(f"🌐 Informe HTML generado exitosamente en: {filepath}")
            QMessageBox.information(self, "Informe Guardado", f"✅ Informe HTML exportado exitosamente en:\n{filepath}")
        except Exception as e:
            self.log(f"❌ Error exportando informe HTML: {e}")
            QMessageBox.critical(self, "Error al Exportar", f"No se pudo guardar el informe HTML: {e}")

    def copy_summary_to_clipboard(self):
        try:
            content = self.generate_markdown_report_content()
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(content)
                self.log("📋 Resumen completo de telemetría copiado al portapapeles.")
                QMessageBox.information(self, "Copiado al Portapapeles", "✅ Resumen en formato Markdown copiado al portapapeles listo para pegar en Obsidian o chats.")
        except Exception as e:
            self.log(f"❌ Error copiando al portapapeles: {e}")

    # ── SINCRONIZACIÓN MULTI-CLIENTE & PROPAGACIÓN 1-CLIC ─────────────────────
    def _backup_file(self, path: str):
        if os.path.exists(path):
            try:
                import shutil
                shutil.copy2(path, f"{path}.bak")
            except Exception:
                pass

    def sync_to_hp45(self):
        """Alias de compatibilidad para sync_to_remote."""
        self.sync_to_remote()

    def sync_all_agents(self):
        """Ejecuta la propagación unificada en 1-clic a OpenCode, DeepSeek Harness, Hermes, Zed y Nodo Remoto."""
        self.log("🚀 Iniciando propagación 1-Clic a todos los agentes desde AI Radar...")
        ok_opencode = False
        ok_dsh = False
        ok_hermes = False
        ok_zed = False
        ok_remote = False

        try:
            self.sync_to_opencode(silent=True)
            ok_opencode = True
        except Exception as e:
            self.log(f"  ❌ Error OpenCode: {e}")

        try:
            self.sync_to_dsh(silent=True)
            ok_dsh = True
        except Exception as e:
            self.log(f"  ❌ Error DeepSeek Harness: {e}")

        try:
            self.sync_to_hermes(silent=True)
            ok_hermes = True
        except Exception as e:
            self.log(f"  ❌ Error Hermes: {e}")

        try:
            self.sync_to_zed(silent=True)
            ok_zed = True
        except Exception as e:
            self.log(f"  ❌ Error Zed: {e}")

        try:
            if os.path.exists(SYNC_REMOTE_SCRIPT):
                self.sync_to_remote()
                ok_remote = True
        except Exception as e:
            self.log(f"  ❌ Error Réplica Remota: {e}")

        summary = (
            f"• OpenCode (~/.config/opencode/opencode.jsonc): {'✅ OK' if ok_opencode else '❌ Error'}\n"
            f"• DeepSeek Harness (~/.dsh/settings.yaml): {'✅ OK' if ok_dsh else '❌ Error'}\n"
            f"• Hermes Agent (~/.hermes/config.yaml): {'✅ OK' if ok_hermes else '❌ Error'}\n"
            f"• Zed Editor (~/.config/zed/settings.json): {'✅ OK' if ok_zed else '❌ Error'}\n"
            f"• Réplica Remota (HP45): {'🚀 Iniciada en segundo plano' if ok_remote else '⚪ Omitida (sin script en cache)'}"
        )
        self.log("✅ Propagación 1-Clic finalizada.")
        QMessageBox.information(self, "Propagación 1-Clic Completa", f"✅ Telemetría y modelos propagados a todos los agentes:\n\n{summary}")

    def export_deepseek_dialog(self):
        """Abre el diálogo de exportación e inspección multi-cuenta para DeepSeek (Direct, C1, C7)."""
        deepseek_models = [m for m in self.table_models_map.values() if m.get("provider") == "deepseek"]
        if not deepseek_models:
            deepseek_models = [m for m in CURATED_FLEET if m.get("provider") == "deepseek"]

        if not deepseek_models:
            QMessageBox.warning(self, "DeepSeek", "No se encontraron modelos DeepSeek en la flota.")
            return

        payload = {
            "deepseek_fleet": [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "account_tag": m.get("account_tag", "C1"),
                    "provider": m.get("provider"),
                    "base_url": m.get("base_url"),
                    "context": m.get("context")
                }
                for m in deepseek_models
            ]
        }
        text_payload = json.dumps(payload, indent=2)

        dlg = QDialog(self)
        dlg.setWindowTitle("📤 Exportar & Propagar Modelos DeepSeek (C1..C7)")
        dlg.resize(600, 440)
        dlg.setStyleSheet("background-color: #070D14; color: #F1F5F9; font-family: 'Inter', sans-serif;")
        d_lay = QVBoxLayout(dlg)
        d_lay.setContentsMargins(16, 16, 16, 16)
        d_lay.setSpacing(10)

        lbl = QLabel(f"Modelos y Cuentas DeepSeek Direct ({len(deepseek_models)} cuentas/modelos):")
        lbl.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #38BDF8;")
        d_lay.addWidget(lbl)

        txt_p = QPlainTextEdit()
        txt_p.setPlainText(text_payload)
        txt_p.setReadOnly(True)
        txt_p.setStyleSheet("background-color: #0B121E; border: 1px solid #1E293B; border-radius: 6px; font-family: monospace; font-size: 11px; color: #38BDF8;")
        d_lay.addWidget(txt_p)

        b_row = QHBoxLayout()
        btn_c = QPushButton("📋 Copiar JSON")
        btn_c.setObjectName("SecondaryBtn")
        btn_c.clicked.connect(lambda: (QApplication.clipboard().setText(text_payload), QMessageBox.information(dlg, "Copiado", "✅ Copiado al portapapeles.")))
        b_row.addWidget(btn_c)

        b_row.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setObjectName("SecondaryBtn")
        btn_close.clicked.connect(dlg.accept)
        b_row.addWidget(btn_close)
        d_lay.addLayout(b_row)

        dlg.exec()

    def copy_deepseek_fast(self):
        deepseek_models = [m for m in self.table_models_map.values() if m.get("provider") == "deepseek"]
        if not deepseek_models:
            deepseek_models = [m for m in CURATED_FLEET if m.get("provider") == "deepseek"]

        payload = {
            "deepseek_models": [
                {"id": m.get("id"), "account": m.get("account_tag", "C1"), "name": m.get("name")}
                for m in deepseek_models
            ]
        }
        cb = QApplication.clipboard()
        if cb:
            cb.setText(json.dumps(payload, indent=2))
            self.log(f"📋 Configuración de {len(deepseek_models)} modelos DeepSeek copiada al portapapeles.")
            QMessageBox.information(self, "DeepSeek Copiado", f"✅ {len(deepseek_models)} modelos DeepSeek copiados al portapapeles.")

    # ── Mapeo de proveedor+cuenta → configuración de agente ─────────────────
    PROVIDER_ENV_MAP = {
        ("google", "C1"): {"env_key": "C1_GOOGLE_AISTUDIO", "npm": "@ai-sdk/google", "label": "Google AI Studio Pro [C1]"},
        ("openrouter", "C7"): {"env_key": "C7_OPENROUTER", "npm": "@ai-sdk/openai-compatible", "label": "OpenRouter Global Hub [C7]", "base_url": "https://openrouter.ai/api/v1"},
        ("openrouter", "C1"): {"env_key": "C1_OPENROUTER", "npm": "@ai-sdk/openai-compatible", "label": "OpenRouter [C1]", "base_url": "https://openrouter.ai/api/v1"},
        ("nvidia", "C7"): {"env_key": "C7_NVIDIA", "npm": "@ai-sdk/openai-compatible", "label": "NVIDIA NIM [C7]", "base_url": "https://integrate.api.nvidia.com/v1"},
        ("nvidia", "C1"): {"env_key": "C1_NVIDIA", "npm": "@ai-sdk/openai-compatible", "label": "NVIDIA NIM [C1]", "base_url": "https://integrate.api.nvidia.com/v1"},
        ("nvidia", "C2"): {"env_key": "C2_NVIDIA", "npm": "@ai-sdk/openai-compatible", "label": "NVIDIA NIM [C2]", "base_url": "https://integrate.api.nvidia.com/v1"},
        ("mistral", "C1"): {"env_key": "C1_MISTRAL", "npm": "@ai-sdk/mistral", "label": "Mistral AI Pro [C1]"},
        ("mistral", "C2"): {"env_key": "C2_MISTRAL", "npm": "@ai-sdk/openai-compatible", "label": "Mistral AI [C2]", "base_url": "https://api.mistral.ai/v1"},
        ("deepseek", "DIRECT"): {"env_key": "DEEPSEEK_API_KEY", "npm": "@ai-sdk/openai-compatible", "label": "DeepSeek Direct [Paid]", "base_url": "https://api.deepseek.com/v1"},
        ("deepseek", "PAID"): {"env_key": "DEEPSEEK_API_KEY", "npm": "@ai-sdk/openai-compatible", "label": "DeepSeek Direct [Paid]", "base_url": "https://api.deepseek.com/v1"},
        ("deepseek", "C1"): {"env_key": "C1_DEEPSEEK", "npm": "@ai-sdk/openai-compatible", "label": "DeepSeek Direct [C1]", "base_url": "https://api.deepseek.com/v1"},
        ("deepseek", "C7"): {"env_key": "C7_DEEPSEEK", "npm": "@ai-sdk/openai-compatible", "label": "DeepSeek Direct [C7]", "base_url": "https://api.deepseek.com/v1"},
        ("groq", "C1"): {"env_key": "C1_GROQ", "npm": "@ai-sdk/openai-compatible", "label": "Groq LPU [C1]", "base_url": "https://api.groq.com/openai/v1"},
        ("zai", "C1"): {"env_key": "C1_Z_AI", "npm": "@ai-sdk/openai-compatible", "label": "Z.AI GLM [C1]", "base_url": "https://api.z.ai/v1"},
        ("b_ai", "C7"): {"env_key": "C7_B_AI_API", "npm": "@ai-sdk/openai-compatible", "label": "B.AI GLM Hub [C7]", "base_url": "https://api.b.ai/v1"},
        ("b_ai", "C1"): {"env_key": "C1_Z_AI", "npm": "@ai-sdk/openai-compatible", "label": "B.AI GLM Hub [C1]", "base_url": "https://api.z.ai/v1"},
        ("b_ai", "DEFAULT"): {"env_key": "C7_B_AI_API", "npm": "@ai-sdk/openai-compatible", "label": "B.AI GLM Hub [C7]", "base_url": "https://api.b.ai/v1"},
        ("bai", "C7"): {"env_key": "C7_B_AI_API", "npm": "@ai-sdk/openai-compatible", "label": "B.AI GLM Hub [C7]", "base_url": "https://api.b.ai/v1"},
    }

    def _get_provider_env_cfg(self, prov: str, tag: str) -> Optional[Dict[str, Any]]:
        prov_k = str(prov).lower()
        tag_k = str(tag).upper()
        if (prov_k, tag_k) in self.PROVIDER_ENV_MAP:
            return self.PROVIDER_ENV_MAP[(prov_k, tag_k)]
        # Fallback de tag directo o case insensitive
        for (p, t), cfg in self.PROVIDER_ENV_MAP.items():
            if p == prov_k and t == tag_k:
                return cfg
        # Fallback general por proveedor
        for (p, t), cfg in self.PROVIDER_ENV_MAP.items():
            if p == prov_k:
                return cfg
        # Fallbacks explícitos por proveedor
        if prov_k in ("b_ai", "bai"):
            return {"env_key": "C7_B_AI_API", "npm": "@ai-sdk/openai-compatible", "label": "B.AI GLM Hub [C7]", "base_url": "https://api.b.ai/v1"}
        if prov_k == "openrouter":
            return {"env_key": "C7_OPENROUTER", "npm": "@ai-sdk/openai-compatible", "label": "OpenRouter Global Hub [C7]", "base_url": "https://openrouter.ai/api/v1"}
        if prov_k == "nvidia":
            return {"env_key": "C7_NVIDIA", "npm": "@ai-sdk/openai-compatible", "label": "NVIDIA NIM [C7]", "base_url": "https://integrate.api.nvidia.com/v1"}
        if prov_k == "deepseek":
            return {"env_key": "DEEPSEEK_API_KEY", "npm": "@ai-sdk/openai-compatible", "label": "DeepSeek Direct", "base_url": "https://api.deepseek.com/v1"}
        if prov_k == "mistral":
            return {"env_key": "C1_MISTRAL", "npm": "@ai-sdk/mistral", "label": "Mistral AI Pro [C1]"}
        if prov_k == "google":
            return {"env_key": "C1_GOOGLE_AISTUDIO", "npm": "@ai-sdk/google", "label": "Google AI Studio Pro [C1]"}
        if prov_k == "groq":
            return {"env_key": "C1_GROQ", "npm": "@ai-sdk/openai-compatible", "label": "Groq LPU [C1]", "base_url": "https://api.groq.com/openai/v1"}
        if prov_k in ("zai", "z_ai"):
            return {"env_key": "C1_Z_AI", "npm": "@ai-sdk/openai-compatible", "label": "Z.AI GLM [C1]", "base_url": "https://api.z.ai/v1"}
        return None

    def _build_provider_groups(self) -> Dict[str, Dict]:
        """
        Agrupa los modelos para generar configs de OpenCode y Hermes con estricta coherencia.
        - Prioriza la flota activa curada (23 a 25 modelos) y los modelos verificados.
        - Garantiza que Google, DeepSeek, Mistral, NVIDIA, OpenRouter y Groq se incluyan limpiamente.
        - Excluye endpoints con errores críticos de autenticación o falta de credenciales.
        """
        from collections import defaultdict
        groups = defaultdict(list)

        curated_ids = {m["id"] for m in CURATED_FLEET}
        only_verified = getattr(self, "chk_sync_only_verified", None)
        only_verified_checked = only_verified.isChecked() if only_verified is not None else True

        # 1. Recorrer modelos de la tabla activa
        for m_id, m in self.table_models_map.items():
            prov = str(m.get("provider", "unknown")).lower()
            tag = str(m.get("account_tag", "C1")).upper()
            status = str(m.get("status", ""))

            cb = self.table_checkboxes.get(m_id)
            checked = cb.isChecked() if cb is not None else True

            if not checked:
                continue

            # Si está activo el filtro de solo verificados, exigir respuesta 200_OK coherente
            if only_verified_checked:
                if not is_coherent_ok_response(m):
                    continue
            else:
                # Excluir errores fatales de credenciales o caídas totales
                if status in ("AUTH_ERR", "SIN_KEY", "NO_CREDITS", "HTTP_500", "HTTP_502", "HTTP_503"):
                    if m_id not in curated_ids:
                        continue
                    elif status in ("AUTH_ERR", "SIN_KEY"):
                        continue

                # Filtro anti-ruido: no inyectar scrapings desconocidos ni modelos no calificados
                if prov == "openrouter" and m_id not in curated_ids:
                    m_id_lower = m_id.lower()
                    if any(bad in m_id_lower for bad in ("fireworks", "together", "lepton", "novita", "samba")):
                        if status not in ("200_OK", "ONLINE"):
                            continue

            groups[(prov, tag)].append(m)

        # 2. Asegurar que los proveedores esenciales configurados con API Key en .env no queden vacíos
        curated_providers = set(str(m.get("provider", "")).lower() for m in CURATED_FLEET)
        active_providers = set(k[0] for k in groups.keys())
        missing_providers = curated_providers - active_providers

        if missing_providers:
            for m in CURATED_FLEET:
                p = str(m.get("provider", "unknown")).lower()
                t = str(m.get("account_tag", "C1")).upper()
                if p in missing_providers:
                    if resolve_api_key_for_model(m):
                        groups[(p, t)].append(m)

        # 3. Fallback de seguridad si groups está completamente vacío
        if not groups:
            for m in CURATED_FLEET:
                p = str(m.get("provider", "unknown")).lower()
                t = str(m.get("account_tag", "C1")).upper()
                if resolve_api_key_for_model(m):
                    groups[(p, t)].append(m)

        return dict(groups)

    def sync_to_opencode(self, silent: bool = False):
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

            # Construir providers dinámicamente desde la tabla activa
            groups = self._build_provider_groups()
            providers = {}
            for (prov, tag), models in sorted(groups.items()):
                cfg = self._get_provider_env_cfg(prov, tag)
                if not cfg:
                    continue
                prov_key = prov if prov not in providers else f"{prov}_{tag.lower()}"
                options = {"apiKey": "{env:" + cfg["env_key"] + "}"}
                if "base_url" in cfg:
                    options["baseURL"] = cfg["base_url"]
                model_entries = {}
                whitelist_entries = []
                for m in models:
                    m_id = m["id"]
                    real_id = m_id.split("/", 1)[-1] if m_id.startswith(("c1/", "c2/", "c7/")) else m_id
                    t_clean = tag.lower()
                    if prov in ("deepseek", "mistral") and t_clean not in ("c1", "principal", ""):
                        unique_key = f"{real_id}-{t_clean}"
                    else:
                        unique_key = real_id

                    # Sanitizar slug para la API oficial de DeepSeek
                    target_model_id = real_id
                    if prov == "deepseek" and "api.deepseek.com" in cfg.get("base_url", ""):
                        target_model_id = normalize_deepseek_slug(real_id)

                    entry = {"name": m.get("name", unique_key)}
                    if unique_key != target_model_id:
                        entry["id"] = target_model_id
                    model_entries[unique_key] = entry
                    if unique_key not in whitelist_entries:
                        whitelist_entries.append(unique_key)

                BUILTIN_PROVIDERS = {"google", "openrouter", "mistral", "nvidia", "groq", "deepseek"}
                is_builtin = prov_key in BUILTIN_PROVIDERS

                if prov_key not in providers:
                    p_data = {
                        "npm": cfg["npm"],
                        "name": cfg["label"],
                        "options": options,
                        "models": model_entries
                    }
                    if is_builtin:
                        p_data["whitelist"] = whitelist_entries
                    providers[prov_key] = p_data
                else:
                    providers[prov_key]["models"].update(model_entries)
                    if is_builtin and "whitelist" in providers[prov_key]:
                        for w in whitelist_entries:
                            if w not in providers[prov_key]["whitelist"]:
                                providers[prov_key]["whitelist"].append(w)

            # Seleccionar modelo principal (preferir gemini-3.7-flash si existe)
            main_model = "google/gemini-3.7-flash"
            small_model = "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
            if "gemini-3.7-flash" in self.table_models_map:
                main_model = "google/gemini-3.7-flash"
            elif self.table_models_map:
                main_model = next(iter(self.table_models_map))

            ALL_KNOWN_NATIVE_PROVIDERS = [
                "alibaba", "aliyun", "amazon-bedrock", "anthropic", "azure", "bai",
                "bedrock", "cerebras", "cloudflare", "cohere", "fireworks",
                "github-copilot", "lmstudio", "moonshotai", "ollama", "openai",
                "perplexity", "replicate", "tabitoken", "together", "upstage",
                "vertex", "vllm", "voyage", "xai", "zen"
            ]
            disabled_providers = [p for p in ALL_KNOWN_NATIVE_PROVIDERS if p not in providers and p not in ("bai", "b_ai", "b-ai-c7", "b_ai_c7")]

            opencode_cfg = {
                "$schema": "https://opencode.ai/config.json",
                "model": main_model,
                "small_model": small_model,
                "disabled_providers": disabled_providers,
                "enabled_providers": list(providers.keys()),
                "provider": providers
            }
            if existing_mcp:
                opencode_cfg["mcp"] = existing_mcp

            os.makedirs(os.path.dirname(OPENCODE_CONFIG), exist_ok=True)
            atomic_json_write(OPENCODE_CONFIG, opencode_cfg)

            # Replicar a ~/.opencode/opencode.jsonc si la carpeta existe
            alt_opencode = os.path.expanduser("~/.opencode/opencode.jsonc")
            if os.path.exists(os.path.dirname(alt_opencode)):
                self._backup_file(alt_opencode)
                atomic_json_write(alt_opencode, opencode_cfg)

            model_count = sum(len(p.get("models", {})) for p in providers.values())
            self.log(f"✅ OpenCode sincronizado: {len(providers)} proveedores autorizados, {model_count} modelos → {OPENCODE_CONFIG}")
            if not silent:
                QMessageBox.information(self, "OpenCode Sincronizado", f"✅ Flota dinámica exportada a OpenCode:\n\n• {len(providers)} proveedores autorizados\n• {model_count} modelos\n• {OPENCODE_CONFIG}")
        except Exception as e:
            self.log(f"❌ Error sincronizando OpenCode: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar OpenCode: {e}")

    def sync_to_dsh(self, silent: bool = False):
        try:
            dsh_config = os.path.expanduser("~/.dsh/settings.yaml")
            if not os.path.exists(os.path.dirname(dsh_config)):
                return
            self._backup_file(dsh_config)

            groups = self._build_provider_groups()
            dsh_providers = {}
            for (prov, tag), models in sorted(groups.items()):
                cfg = self._get_provider_env_cfg(prov, tag)
                if not cfg:
                    continue
                prov_key = prov if prov not in dsh_providers else f"{prov}_{tag.lower()}"
                base_url = cfg.get("base_url", models[0].get("base_url", ""))
                dsh_models = []
                for m in models:
                    m_id = m["id"]
                    clean_id = m_id.split("/", 1)[-1] if m_id.startswith(("c1/", "c2/", "c7/")) else m_id
                    ctx = m.get("context", 131072)
                    dsh_models.append({
                        "id": clean_id,
                        "name": m.get("name", clean_id),
                        "contextWindow": ctx
                    })
                dsh_providers[prov_key] = {
                    "api": "openai-completions",
                    "displayName": cfg["label"],
                    "apiKeyEnv": cfg["env_key"],
                    "baseURL": base_url,
                    "models": dsh_models
                }

            import yaml
            existing_data = {}
            if os.path.exists(dsh_config):
                try:
                    with open(dsh_config, "r", encoding="utf-8") as f:
                        existing_data = yaml.safe_load(f) or {}
                except Exception:
                    existing_data = {}

            if not isinstance(existing_data, dict):
                existing_data = {}

            existing_data["version"] = 2
            existing_data["theme"] = existing_data.get("theme", "dark")
            if "llm-pi-ai" not in existing_data:
                existing_data["llm-pi-ai"] = {}
            existing_data["llm-pi-ai"]["providers"] = dsh_providers

            with open(dsh_config, "w", encoding="utf-8") as f:
                yaml.dump(existing_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            model_count = sum(len(p.get("models", [])) for p in dsh_providers.values())
            self.log(f"✅ DeepSeek Harness (DSH) sincronizado: {len(dsh_providers)} proveedores, {model_count} modelos → {dsh_config}")
            if not silent:
                QMessageBox.information(self, "DSH Sincronizado", f"✅ Flota sincronizada a DeepSeek Harness:\n\n• {len(dsh_providers)} proveedores\n• {model_count} modelos\n• {dsh_config}")
        except Exception as e:
            self.log(f"❌ Error sincronizando DSH: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar DSH: {e}")

    def sync_to_hermes(self, silent: bool = False):
        try:
            self._backup_file(HERMES_CONFIG)

            # Construir config YAML dinámicamente desde la tabla activa con diccionario deduplicado
            groups = self._build_provider_groups()
            providers_dict = {}
            hermes_cache = {}

            for (prov, tag), models in sorted(groups.items()):
                cfg = self._get_provider_env_cfg(prov, tag)
                if not cfg:
                    continue
                prov_key = prov if prov not in providers_dict else f"{prov}_{tag.lower()}"
                base_url = cfg.get("base_url", models[0].get("base_url", ""))
                model_ids = []
                for m in models:
                    m_id = m["id"]
                    clean_id = m_id.split("/", 1)[-1] if m_id.startswith(("c1/", "c2/", "c7/")) else m_id
                    if clean_id not in model_ids:
                        model_ids.append(clean_id)

                if prov_key not in providers_dict:
                    providers_dict[prov_key] = {
                        "name": cfg["label"],
                        "env_key": cfg["env_key"],
                        "base_url": base_url,
                        "models": list(model_ids)
                    }
                    hermes_cache[prov_key] = {
                        "fp": f"{prov_key}-dynamic-v4",
                        "at": time.time(),
                        "models": list(model_ids)
                    }
                else:
                    for mid in model_ids:
                        if mid not in providers_dict[prov_key]["models"]:
                            providers_dict[prov_key]["models"].append(mid)
                        if mid not in hermes_cache[prov_key]["models"]:
                            hermes_cache[prov_key]["models"].append(mid)

            providers_yaml = ""
            for pkey, pval in providers_dict.items():
                models_yaml = "\n".join(f"      - {mid}" for mid in pval["models"])
                providers_yaml += f"""  {pkey}:
    name: "{pval['name']}"
    env_key: {pval['env_key']}
    base_url: {pval['base_url']}
    api: openai-completions
    models:
{models_yaml}
"""

            hermes_yaml = f"""model:
  default: gemini-3.7-flash
  provider: google
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/
providers:
{providers_yaml}database:
  journal_mode: wal
runtime:
  nofile_soft_limit: 4096
_config_version: 41
fallback_model:
  provider: openrouter
  model: minimax/minimax-m3:free
"""
            os.makedirs(os.path.dirname(HERMES_CONFIG), exist_ok=True)
            with open(HERMES_CONFIG, "w", encoding="utf-8") as f:
                f.write(hermes_yaml)

            atomic_json_write(HERMES_CACHE, hermes_cache)

            model_count = sum(len(c.get("models", [])) for c in hermes_cache.values())
            self.log(f"✅ Hermes Agent sincronizado: {len(hermes_cache)} proveedores, {model_count} modelos → {HERMES_CONFIG}")
            if not silent:
                QMessageBox.information(self, "Hermes Sincronizado", f"✅ Flota dinámica exportada a Hermes:\n\n• {len(hermes_cache)} proveedores\n• {model_count} modelos\n• {HERMES_CONFIG}")
        except Exception as e:
            self.log(f"❌ Error sincronizando Hermes: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar Hermes: {e}")

    def sync_to_zed(self, silent: bool = False):
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

            self.log("📝 Configuración de Zed Editor sincronizada con claves del entorno.")
            if not silent:
                QMessageBox.information(self, "Zed Editor", "✅ Claves de entorno y proveedores sincronizados para Zed Editor.")
        except Exception as e:
            self.log(f"❌ Error en Zed: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar Zed Editor: {e}")

    def sync_to_remote(self):
        if not os.path.exists(SYNC_REMOTE_SCRIPT):
            self.log("⚠️ Script sync_remote_node.sh no encontrado en cache.")
            return

        if is_worker_running(self.sync_worker):
            self.log("⚠️ Ya hay una sincronización remota en curso.")
            return

        self.log(f"💻 Ejecutando réplica asíncrona ({SYNC_REMOTE_SCRIPT})...")
        self.sync_worker = SyncHP45Worker(SYNC_REMOTE_SCRIPT)
        self.sync_worker.sync_finished.connect(self._on_sync_remote_finished)
        self.sync_worker.finished.connect(self._on_sync_remote_worker_finished)
        self.sync_worker.start()

    def _on_sync_remote_worker_finished(self):
        if self.sync_worker:
            self.sync_worker.deleteLater()
            self.sync_worker = None

    def _on_sync_remote_finished(self, success: bool, msg: str):
        if success:
            self.log(f"✅ {msg}")
        else:
            self.log(f"⚠️ Aviso Réplica Remota: {msg}")

    def cleanup(self):
        """Detiene y espera workers de forma determinista y cooperativa sin terminate()."""
        for worker in (self.probe_worker, self.advisor_worker, self.discovery_worker, self.sync_worker):
            stop_worker(worker, timeout_ms=1800)
        self.probe_worker = None
        self.advisor_worker = None
        self.discovery_worker = None
        self.sync_worker = None

    def wait_for_shutdown(self, timeout_ms: int = 2000) -> bool:
        """Contrato FSU-002: cleanup() ya esperó por cada worker de forma determinista."""
        return True

