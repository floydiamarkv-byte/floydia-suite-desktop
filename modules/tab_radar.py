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
SYNC_REMOTE_SCRIPT = os.path.join(CACHE_DIR, "sync_remote_node.sh")
REPORTS_DIR = os.path.join(WORKSPACE_ROOT, "reports")
CACHE_DIR = os.path.join(WORKSPACE_ROOT, "cache")
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


def atomic_json_write(path: str, data: dict) -> None:
    """Escritura atómica thread-safe y multi-proceso con fcntl.flock y reemplazo seguro."""
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
    if not snip or snip in ("—", "sin probar", "sondeo cancelado"):
        return False
    bad_keywords = (
        "sin créditos", "insufficient credits", "out of credits", "no credits",
        "quota", "rate limit", "error", "timeout", "payment required", "402",
        "balance is too low", "exceeded your current quota", "unauthorized", "invalid key",
        "credit is not enough"
    )
    if any(kw in snip for kw in bad_keywords):
        return False
    return True


# Cargar variables de .env
def load_env_vars() -> Dict[str, str]:
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

ENV_MAP = load_env_vars()

def get_secret(keys: List[str]) -> Optional[str]:
    for k in keys:
        if k in os.environ and os.environ[k]:
            return os.environ[k]
        if k in ENV_MAP and ENV_MAP[k]:
            return ENV_MAP[k]
    return None

# Secretos Multi-Cuenta
GOOGLE_C1_KEY = get_secret(["C1_GOOGLE_AISTUDIO", "GOOGLE_AI_STUDIO_API_KEY", "GOOGLE_API_KEY"])
GOOGLE_C2_KEY = get_secret(["C2_GOOGLE_AISTUDIO"])
OPENROUTER_C7_KEY = get_secret(["C7_OPENROUTER_OPENCODE_HP15", "OPENROUTER_API_KEY", "C7_OPENROUTER", "C1_OPENROUTER"])
OPENROUTER_C1_KEY = get_secret(["C1_OPENROUTER"])
NVIDIA_C7_KEY = get_secret(["C7_NVIDIA", "NVIDIA_API_KEY"])
NVIDIA_C1_KEY = get_secret(["C1_NVIDIA"])
NVIDIA_C2_KEY = get_secret(["C2_NVIDIA"])
MISTRAL_C1_KEY = get_secret(["C1_MISTRAL", "MISTRAL_API_KEY"])
MISTRAL_C2_KEY = get_secret(["C2_MISTRAL"])
DEEPSEEK_DIRECT_KEY = get_secret(["DEEPSEEK_API_KEY"])
DEEPSEEK_C1_KEY = get_secret(["C1_DEEPSEEK"])
DEEPSEEK_C7_KEY = get_secret(["C7_DEEPSEEK"])
GROQ_C1_KEY = get_secret(["C1_GROQ"])
ZAI_C1_KEY = get_secret(["C1_Z_AI"])

# Alias y Claves Globales Canónicas para Catálogo Global, Advisor y Fallbacks
GOOGLE_KEY = GOOGLE_C1_KEY or GOOGLE_C2_KEY
OPENROUTER_KEY = OPENROUTER_C7_KEY or OPENROUTER_C1_KEY
NVIDIA_KEY = NVIDIA_C7_KEY or NVIDIA_C1_KEY or NVIDIA_C2_KEY
MISTRAL_KEY = MISTRAL_C1_KEY or MISTRAL_C2_KEY
DEEPSEEK_KEY = DEEPSEEK_DIRECT_KEY or DEEPSEEK_C1_KEY or DEEPSEEK_C7_KEY
GROQ_KEY = GROQ_C1_KEY
ZAI_KEY = ZAI_C1_KEY

# Flota Curada de Modelos IA de FloydIA Homelab con Taxonomía Multi-Cuenta [C1..C8]
CURATED_FLEET = [
    # Google AI Studio [C1] y [C2]
    {"id": "gemini-3.7-flash", "name": "[C1] Gemini 3.7 Flash Reasoning", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "c2/gemini-3.7-flash", "name": "[C2] Gemini 3.7 Flash Reasoning", "account_tag": "C2", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C2_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-3.6-flash", "name": "[C1] Gemini 3.6 Flash Fast", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemini-3.5-flash", "name": "[C1] Gemini 3.5 Flash Multimodal", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 1048576, "badge": "1M • Pro", "category": "frontier"},
    {"id": "gemma-4-31b-it", "name": "[C1] Gemma 4 31B Instruct", "account_tag": "C1", "provider": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": GOOGLE_C1_KEY, "context": 262144, "badge": "262k • Pro", "category": "frontier"},

    # OpenRouter Hub [C7] y [C1]
    {"id": "openrouter/auto", "name": "[C7] OpenRouter Auto Router", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 262144, "badge": "Auto • Free", "category": "free"},
    {"id": "openrouter/free", "name": "[C7] OpenRouter Free Cluster", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 262144, "badge": "Auto • Free", "category": "free"},
    {"id": "minimax/minimax-m3:free", "name": "[C7] MiniMax M3 Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 1048576, "badge": "1M • Free", "category": "free"},
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "name": "[C7] Nemotron 3 Super 120B", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 262144, "badge": "262k • Free", "category": "free"},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "name": "[C7] Nemotron 3 Nano Reasoning", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 256000, "badge": "256k • Free", "category": "free"},
    {"id": "z-ai/glm-5.2:free", "name": "[C7] GLM 5.2 Frontier", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 256000, "badge": "256k • Free", "category": "free"},
    {"id": "poolside/laguna-s-2.1:free", "name": "[C7] Laguna S 2.1 Code", "account_tag": "C7", "provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "key": OPENROUTER_C7_KEY, "context": 262144, "badge": "262k • Free", "category": "code"},

    # NVIDIA NIM [C7], [C1], [C2]
    {"id": "deepseek-ai/deepseek-v4-flash-0731", "name": "[C1] DeepSeek V4 Flash (NIM)", "account_tag": "C1", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C1_KEY or NVIDIA_C7_KEY, "context": 262144, "badge": "256k • NIM", "category": "code"},
    {"id": "moonshotai/kimi-k3", "name": "[C2] Kimi K3 Frontier (NIM)", "account_tag": "C2", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C2_KEY or NVIDIA_C7_KEY, "context": 262144, "badge": "256k • NIM", "category": "frontier"},
    {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "name": "[C7] Nemotron 3 Nano NIM", "account_tag": "C7", "provider": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1", "key": NVIDIA_C7_KEY, "context": 256000, "badge": "256k • NIM", "category": "frontier"},

    # Mistral AI [C1] y [C2]
    {"id": "codestral-latest", "name": "[C1] Mistral Codestral Latest", "account_tag": "C1", "provider": "mistral", "base_url": "https://api.mistral.ai/v1", "key": MISTRAL_C1_KEY, "context": 256000, "badge": "256k • Trial", "category": "code"},
    {"id": "c2/codestral-latest", "name": "[C2] Mistral Codestral Latest", "account_tag": "C2", "provider": "mistral", "base_url": "https://api.mistral.ai/v1", "key": MISTRAL_C2_KEY, "context": 256000, "badge": "256k • Trial", "category": "code"},

    # DeepSeek Direct [Direct], [C1], [C7]
    {"id": "deepseek-chat", "name": "[Direct] DeepSeek Chat V3 Paid", "account_tag": "Direct", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Paid", "category": "frontier"},
    {"id": "c1/deepseek-chat", "name": "[C1] DeepSeek Chat V3", "account_tag": "C1", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C1_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},
    {"id": "c7/deepseek-chat", "name": "[C7] DeepSeek Chat V3", "account_tag": "C7", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "key": DEEPSEEK_C7_KEY or DEEPSEEK_DIRECT_KEY, "context": 128000, "badge": "128k • Direct", "category": "frontier"},
]

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

    key = item.get("key")
    if not key:
        return {"status": "SIN_KEY", "latency_ms": 0, "response_snippet": "Sin API Key configurada en .env", "error": "Sin API Key"}

    base_url = item["base_url"].rstrip("/")
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

    payload = {
        "model": item["id"],
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
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                t_end = time.monotonic()
                timing = Timing(request_start=t_start, first_chunk=None, response_end=t_end)
                latency = timing.total_ms

                if resp.status == 200:
                    body = json.loads(resp.read().decode("utf-8"))
                    snippet = "OK"
                    try:
                        raw_content = body["choices"][0]["message"]["content"]
                        snippet = raw_content.strip().replace("\n", " ")
                        if len(snippet) > 80:
                            snippet = snippet[:77] + "..."
                    except Exception:
                        pass

                    usage = body.get("usage", {})
                    out_tokens = usage.get("completion_tokens", 0)
                    tps = calculate_tps(out_tokens, timing)

                    snip_lower = snippet.lower()
                    if any(kw in snip_lower for kw in no_credit_keywords) or snip_lower.startswith('{"error"'):
                        return {
                            "status": "NO_CREDITS",
                            "latency_ms": latency,
                            "response_snippet": f"⚠️ Sin créditos / Error: {snippet[:60]}",
                            "tokens": out_tokens,
                            "tps": tps,
                            "error": "Insufficient Credits"
                        }

                    return {
                        "status": "200_OK",
                        "latency_ms": latency,
                        "response_snippet": snippet,
                        "tokens": out_tokens,
                        "tps": tps,
                        "error": None
                    }
                return {"status": f"HTTP_{resp.status}", "latency_ms": latency, "response_snippet": f"Status {resp.status}", "error": f"Status {resp.status}"}
        except urllib.error.HTTPError as e:
            latency = int((time.monotonic() - t_start) * 1000)
            if e.code == 402:
                return {"status": "NO_CREDITS", "latency_ms": latency, "response_snippet": "402 Pago Requerido / Sin créditos", "error": "Payment Required"}
            if e.code in (401, 403):
                return {"status": "AUTH_ERR", "latency_ms": latency, "response_snippet": f"HTTP {e.code} Clave Inválida / No Autorizado", "error": f"Auth {e.code}"}
            if e.code == 429:
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
                return {"status": "429_LIMIT", "latency_ms": latency, "response_snippet": "Rate limit / Cuota agotada", "error": "Rate limit"}
            if 500 <= e.code < 600 and attempt < max_retries:
                if cancellable_backoff(cancel_event, 0.6 * (2 ** attempt)):
                    return {"status": "CANCELLED", "latency_ms": latency, "response_snippet": "Sondeo cancelado", "error": "cancelled"}
                continue
            return {"status": f"HTTP_{e.code}", "latency_ms": latency, "response_snippet": f"HTTP {e.code}", "error": str(e)[:30]}
        except Exception as e:
            latency = int((time.monotonic() - t_start) * 1000)
            if attempt < max_retries:
                if cancellable_backoff(cancel_event, 0.5):
                    return {"status": "CANCELLED", "latency_ms": latency, "response_snippet": "Sondeo cancelado", "error": "cancelled"}
                continue
            return {"status": "TIMEOUT_ERR", "latency_ms": latency, "response_snippet": "Timeout o falla de red", "error": str(e)[:30]}


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

        with ThreadPoolExecutor(max_workers=min(16, max(1, len(self.fleet)))) as executor:
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
                    st = res.get("status", "ERR")
                    lat = f"{res.get('latency_ms', 0)} ms" if res.get("latency_ms", 0) > 0 else "-"
                    tps_str = f" • {res.get('tps', 0)} TPS" if res.get('tps', 0) > 0 else ""
                    self.log_signal.emit(f"  • {m['name']}: {st} ({lat}{tps_str}) — {res.get('response_snippet', '')}")
                except Exception as e:
                    err_item = {**m, "status": "ERROR", "latency_ms": 0, "response_snippet": str(e), "error": str(e)}
                    results.append(err_item)
                    self.model_updated.emit(err_item)

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

    def __init__(self, openrouter_key: Optional[str], nvidia_key: Optional[str], google_key: Optional[str], mistral_key: Optional[str], options: dict):
        super().__init__()
        self.openrouter_key = openrouter_key
        self.nvidia_key = nvidia_key
        self.google_key = google_key
        self.mistral_key = mistral_key
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
                with open(RADAR_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("models", []):
                        if "id" in item and item.get("latency_ms", 0) > 0:
                            lat_map[item["id"]] = item["latency_ms"]
            except Exception:
                pass
        return lat_map

    def save_cached_telemetry(self, results: List[Dict[str, Any]]):
        try:
            # P0 Security: Sanitizar y purgar cualquier clave API antes de persistir a disco
            safe_results = sanitize_for_persistence(results)
            cache_payload = {
                "timestamp": datetime.datetime.now().isoformat(),
                "total_models": len(safe_results),
                "models": safe_results
            }
            atomic_json_write(RADAR_CACHE_FILE, cache_payload)
        except Exception:
            pass

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

    def update_kpi_dashboard(self, results: Optional[List[dict]] = None):
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
        self.log("🧹 Tabla restablecida a los 16 modelos esenciales de la Flota Curada FloydIA.")
        QMessageBox.information(self, "Flota Restablecida", "✅ Tabla restablecida a los 16 modelos esenciales de FloydIA.")

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
        if not OPENROUTER_KEY and not NVIDIA_KEY and not GOOGLE_KEY and not MISTRAL_KEY:
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
        self.discovery_worker = CatalogDiscoveryWorker(OPENROUTER_KEY, NVIDIA_KEY, GOOGLE_KEY, MISTRAL_KEY, options)
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
            self.table_models_map = {m["id"]: dict(m) for m in discovered_models}
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

    def sync_all_agents(self):
        """Ejecuta la propagación unificada en 1-clic a OpenCode, Hermes, Zed y HP45."""
        self.log("🚀 Iniciando propagación 1-Clic a todos los agentes desde AI Radar...")
        ok_opencode = False
        ok_hermes = False
        ok_zed = False

        try:
            self.sync_to_opencode(silent=True)
            ok_opencode = True
        except Exception as e:
            self.log(f"  ❌ Error OpenCode: {e}")

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

        self.sync_to_hp45()

        summary = (
            f"• OpenCode (~/.config/opencode/opencode.jsonc): {'✅ OK' if ok_opencode else '❌ Error'}\n"
            f"• Hermes Agent (~/.hermes/config.yaml): {'✅ OK' if ok_hermes else '❌ Error'}\n"
            f"• Zed Editor (~/.config/zed/settings.json): {'✅ OK' if ok_zed else '❌ Error'}\n"
            f"• Réplica HP45: 🚀 Iniciada en segundo plano"
        )
        self.log("✅ Propagación 1-Clic finalizada.")
        QMessageBox.information(self, "Propagación 1-Clic Completa", f"✅ Telemetría y modelos propagados a todos los agentes:\n\n{summary}")

    def export_deepseek_dialog(self):
        """Abre el diálogo de exportación e inspección multi-cuenta para DeepSeek."""
        deepseek_models = [m for m in self.table_models_map.values() if m.get("provider") == "deepseek" or "deepseek" in m.get("id", "").lower()]
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

        lbl = QLabel("Modelos y Cuentas DeepSeek Activas:")
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
        deepseek_models = [m for m in self.table_models_map.values() if m.get("provider") == "deepseek" or "deepseek" in m.get("id", "").lower()]
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

            opencode_cfg = {
                "$schema": "https://opencode.ai/config.json",
                "model": "google/gemini-3.7-flash",
                "small_model": "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "provider": {
                    "google": {
                        "npm": "@ai-sdk/google",
                        "name": "Google AI Studio Pro [C1]",
                        "options": {"apiKey": "{env:C1_GOOGLE_AISTUDIO}"},
                        "models": {
                            "gemini-3.7-flash": {"name": "[C1] Gemini 3.7 (Reasoning)"},
                            "gemini-3.6-flash": {"name": "[C1] Gemini 3.6 (Fast)"},
                            "gemini-3.5-flash": {"name": "[C1] Gemini 3.5 (Multi)"},
                            "gemma-4-31b-it": {"name": "[C1] Gemma 4 31B (Agent)"}
                        }
                    },
                    "google_c2": {
                        "npm": "@ai-sdk/google",
                        "name": "Google AI Studio [C2]",
                        "options": {"apiKey": "{env:C2_GOOGLE_AISTUDIO}"},
                        "models": {
                            "gemini-3.7-flash": {"name": "[C2] Gemini 3.7 (Reasoning)"}
                        }
                    },
                    "mistral": {
                        "npm": "@ai-sdk/mistral",
                        "name": "Mistral AI Pro [C1]",
                        "options": {"apiKey": "{env:C1_MISTRAL}"},
                        "models": {"codestral-latest": {"name": "[C1] Codestral (Code)"}}
                    },
                    "openrouter": {
                        "npm": "@ai-sdk/openai",
                        "name": "OpenRouter Free [C7]",
                        "options": {"baseURL": "https://openrouter.ai/api/v1", "apiKey": "{env:C7_OPENROUTER_OPENCODE_HP15}"},
                        "models": {
                            "openrouter/auto": {"name": "[C7] OpenRouter Auto"},
                            "openrouter/free": {"name": "[C7] OpenRouter Free"},
                            "meta-llama/llama-3.3-70b-instruct:free": {"name": "[C7] Llama 3.3 70B (Free)"},
                            "qwen/qwen-2.5-coder-32b-instruct:free": {"name": "[C7] Qwen 2.5 Coder (Free)"},
                            "deepseek/deepseek-r1:free": {"name": "[C7] DeepSeek R1 (Free)"},
                            "google/gemini-2.0-flash-exp:free": {"name": "[C7] Gemini 2.0 Flash (Free)"},
                            "minimax/minimax-m3:free": {"name": "[C7] MiniMax M3 (Frontier)"},
                            "nvidia/nemotron-3-super-120b-a12b:free": {"name": "[C7] Nemotron 3 Super"},
                            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": {"name": "[C7] Nemotron 3 Nano"},
                            "z-ai/glm-5.2:free": {"name": "[C7] GLM 5.2 (Frontier)"},
                            "poolside/laguna-s-2.1:free": {"name": "[C7] Laguna S 2.1 (Code)"}
                        }
                    },
                    "nvidia": {
                        "npm": "@ai-sdk/openai",
                        "name": "NVIDIA NIM [C7]",
                        "options": {"baseURL": "https://integrate.api.nvidia.com/v1", "apiKey": "{env:C7_NVIDIA}"},
                        "models": {
                            "deepseek-ai/deepseek-v4-flash-0731": {"name": "[C1] DeepSeek V4 (NIM)"},
                            "moonshotai/kimi-k3": {"name": "[C2] Kimi K3 (NIM)"},
                            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": {"name": "[C7] Nemotron 3 Nano (NIM)"}
                        }
                    },
                    "deepseek": {
                        "npm": "@ai-sdk/openai",
                        "name": "DeepSeek Direct [Paid]",
                        "options": {"baseURL": "https://api.deepseek.com/v1", "apiKey": "{env:DEEPSEEK_API_KEY}"},
                        "models": {
                            "deepseek-chat": {"name": "[Direct] DeepSeek Chat V3"},
                            "deepseek-reasoner": {"name": "[Direct] DeepSeek Reasoner R1"}
                        }
                    },
                    "deepseek_c1": {
                        "npm": "@ai-sdk/openai",
                        "name": "DeepSeek Direct [C1]",
                        "options": {"baseURL": "https://api.deepseek.com/v1", "apiKey": "{env:C1_DEEPSEEK}"},
                        "models": {
                            "deepseek-chat": {"name": "[C1] DeepSeek Chat V3"},
                            "deepseek-reasoner": {"name": "[C1] DeepSeek Reasoner R1"}
                        }
                    }
                }
            }
            if existing_mcp:
                opencode_cfg["mcp"] = existing_mcp

            os.makedirs(os.path.dirname(OPENCODE_CONFIG), exist_ok=True)
            atomic_json_write(OPENCODE_CONFIG, opencode_cfg)
            self.log(f"✅ OpenCode sincronizado: {OPENCODE_CONFIG}")
            if not silent:
                QMessageBox.information(self, "OpenCode Sincronizado", f"✅ Flota multi-cuenta exportada exitosamente a:\n{OPENCODE_CONFIG}")
        except Exception as e:
            self.log(f"❌ Error sincronizando OpenCode: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar OpenCode: {e}")

    def sync_to_hermes(self, silent: bool = False):
        try:
            self._backup_file(HERMES_CONFIG)
            hermes_yaml = """model:
  default: gemini-3.7-flash
  provider: google
  base_url: https://generativelanguage.googleapis.com/v1beta/openai/
providers:
  google:
    name: Google AI Studio Pro [C1]
    env_key: C1_GOOGLE_AISTUDIO
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    api: openai-completions
    models:
      - gemini-3.7-flash
      - gemini-3.6-flash
      - gemini-3.5-flash
      - gemma-4-31b-it
  google_c2:
    name: Google AI Studio [C2]
    env_key: C2_GOOGLE_AISTUDIO
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    api: openai-completions
    models:
      - gemini-3.7-flash
  openrouter:
    name: OpenRouter Free [C7]
    env_key: C7_OPENROUTER_OPENCODE_HP15
    base_url: https://openrouter.ai/api/v1
    api: openai-completions
    models:
      - openrouter/auto
      - openrouter/free
      - meta-llama/llama-3.3-70b-instruct:free
      - qwen/qwen-2.5-coder-32b-instruct:free
      - deepseek/deepseek-r1:free
      - google/gemini-2.0-flash-exp:free
      - minimax/minimax-m3:free
      - nvidia/nemotron-3-super-120b-a12b:free
      - nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
      - z-ai/glm-5.2:free
      - poolside/laguna-s-2.1:free
  nvidia:
    name: NVIDIA NIM [C7]
    env_key: C7_NVIDIA
    base_url: https://integrate.api.nvidia.com/v1
    api: openai-completions
    models:
      - deepseek-ai/deepseek-v4-flash-0731
      - moonshotai/kimi-k3
      - nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
  mistral:
    name: Mistral AI Pro [C1]
    env_key: C1_MISTRAL
    base_url: https://api.mistral.ai/v1
    api: openai-completions
    models:
      - codestral-latest
  deepseek:
    name: DeepSeek Direct [Paid]
    env_key: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com/v1
    api: openai-completions
    models:
      - deepseek-chat
      - deepseek-reasoner
  deepseek_c1:
    name: DeepSeek Direct [C1]
    env_key: C1_DEEPSEEK
    base_url: https://api.deepseek.com/v1
    api: openai-completions
    models:
      - deepseek-chat
      - deepseek-reasoner
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
                f.write(hermes_yaml)

            hermes_clean_cache = {
                "google": {"fp": "google-curated-v3", "at": time.time(), "models": ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemma-4-31b-it"]},
                "openrouter": {"fp": "openrouter-curated-v3", "at": time.time(), "models": ["openrouter/auto", "openrouter/free", "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "deepseek/deepseek-r1:free", "google/gemini-2.0-flash-exp:free", "minimax/minimax-m3:free", "nvidia/nemotron-3-super-120b-a12b:free", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "z-ai/glm-5.2:free", "poolside/laguna-s-2.1:free"]},
                "nvidia": {"fp": "nvidia-curated-v3", "at": time.time(), "models": ["deepseek-ai/deepseek-v4-flash-0731", "moonshotai/kimi-k3", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"]},
                "mistral": {"fp": "mistral-curated-v3", "at": time.time(), "models": ["codestral-latest"]},
                "deepseek": {"fp": "deepseek-curated-v3", "at": time.time(), "models": ["deepseek-chat", "deepseek-reasoner"]}
            }
            atomic_json_write(HERMES_CACHE, hermes_clean_cache)

            self.log(f"✅ Hermes Agent sincronizado y purgado: {HERMES_CONFIG}")
            if not silent:
                QMessageBox.information(self, "Hermes Sincronizado", f"✅ Hermes Agent configurado en:\n{HERMES_CONFIG}")
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

