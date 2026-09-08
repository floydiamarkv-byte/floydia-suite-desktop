"""Tests de tab_radar.py: parseo SSE y TTFT real por streaming end-to-end."""
import http.server
import socketserver
import threading

import pytest

pytest.importorskip("PyQt6")

from modules.tab_radar import _sse_extract_event, probe_single_endpoint  # noqa: E402

SSE_EVENTS = [
    '{"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}',
    '{"choices":[{"delta":{"content":"Hola "},"finish_reason":null}]}',
    '{"choices":[{"delta":{"content":"mundo"},"finish_reason":"stop"}]}',
    '{"usage":{"completion_tokens":6},"choices":[]}',
]


class _SSEHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        _len = int(self.headers.get("Content-Length", 0))
        self.rfile.read(_len)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for ev in SSE_EVENTS:
            self.wfile.write(b"data: " + ev.encode("utf-8") + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


def test_sse_extract_event_handles_valid_and_noise():
    assert _sse_extract_event(b'data: {"choices":[{"delta":{"content":"Hola"}}]}')["choices"][0]["delta"]["content"] == "Hola"
    assert _sse_extract_event(b"data: [DONE]") is None
    assert _sse_extract_event(b"") is None
    assert _sse_extract_event(b"event: ping") is None
    assert _sse_extract_event(b"data: not-json{") is None


def test_probe_streaming_ttft_local_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _SSEHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        res = probe_single_endpoint(
            {"id": "test-model", "base_url": f"http://127.0.0.1:{port}/v1",
             "provider": "test", "key": "sk-dummy"},
            {"prompt": "hola", "max_tokens": 8, "timeout": 5},
        )
    finally:
        srv.shutdown()

    assert res.get("status") == "200_OK", res
    assert res.get("metric_mode") == "streaming", res
    assert res.get("ttft_ms") is not None and res.get("ttft_ms") >= 0, res
    assert "Hola mundo" in res.get("response_snippet", ""), res
    assert res.get("tokens") == 6, res
    assert res.get("tps", 0) > 0, res


def test_parity_audit_worker_contract(monkeypatch):
    import modules.tab_radar as tradar
    assert hasattr(tradar, "ParityAuditWorker"), "tab_radar debe definir ParityAuditWorker como QThread/CancellableThread"

    class MockProcess:
        returncode = 0
        stdout = "🎉 [CERTIFICADO 100% PARITARIO]\nOK"

    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MockProcess())
    worker = tradar.ParityAuditWorker()
    emitted = []
    worker.audit_finished.connect(lambda ok, out: emitted.append((ok, out)))
    worker.run()
    assert len(emitted) == 1
    assert emitted[0][0] is True
    assert "CERTIFICADO 100% PARITARIO" in emitted[0][1]


import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def _run_isolated_code(code: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Ejecuta código PyQt6 en un subproceso completamente aislado con PYTHONPATH y cwd anclados."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = REPO_ROOT + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")
    full_code = f"import sys\nif {repr(REPO_ROOT)} not in sys.path:\n    sys.path.insert(0, {repr(REPO_ROOT)})\n" + code
    return subprocess.run(
        [sys.executable, "-c", full_code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


def test_radar_sync_only_verified_persistence():
    """Valida que la preferencia del checkbox 'Solo Verificados' persista en save_state y restore_state."""
    code = (
        "import os, sys\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "import modules.tab_radar as tradar\n"
        "tab = tradar.TabRadar()\n"
        "assert tab.chk_sync_only_verified.isChecked() is True\n"
        "tab.chk_sync_only_verified.setChecked(False)\n"
        "s = tab.save_state()\n"
        "assert s.get('sync_only_verified') is False\n"
        "tab.restore_state({'sync_only_verified': True, 'models': {}})\n"
        "assert tab.chk_sync_only_verified.isChecked() is True\n"
        "tab.restore_state({'sync_only_verified': False, 'models': {}})\n"
        "assert tab.chk_sync_only_verified.isChecked() is False\n"
        "print('PASS')\n"
    )
    res = _run_isolated_code(code)
    assert res.returncode == 0, res.stderr
    assert "PASS" in res.stdout


def test_radar_bai_categorically_excluded_from_auto_injection():
    """Valida que b_ai esté desmarcado por defecto y no se auto-inyecte en los grupos de proveedores."""
    code = (
        "import os, sys\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "import modules.tab_radar as tradar\n"
        "tab = tradar.TabRadar()\n"
        "groups = tab._build_provider_groups()\n"
        "for prov, _ in groups.keys():\n"
        "    assert prov not in ('b_ai', 'bai', 'b-ai-c7', 'b_ai_c7')\n"
        "print('PASS')\n"
    )
    res = _run_isolated_code(code)
    assert res.returncode == 0, res.stderr
    assert "PASS" in res.stdout


def test_radar_defensive_sync_to_opencode_prevents_whack_a_mole(tmp_path):
    """Valida que sync_to_opencode aplique merge defensivo sobre el SSOT sin recortar modelos preexistentes."""
    import json
    fake_ssot = tmp_path / "opencode.jsonc"
    mock_data = {
        "$schema": "https://opencode.ai/config.json",
        "model": "google/gemini-3.7-flash",
        "small_model": "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "disabled_providers": ["alibaba", "bai", "b_ai"],
        "enabled_providers": ["google", "experientiallabs", "nvidia_c9"],
        "provider": {
            "google": {
                "name": "Google AI Studio",
                "options": {"apiKey": "{env:C1_GEMINI_API}"},
                "models": {
                    "gemini-3.7-flash": {"name": "[1.0M] Gemini 3.7 Flash", "context": 1048576},
                    "gemini-3.6-flash": {"name": "[1.0M] Gemini 3.6 Flash", "context": 1048576}
                }
            },
            "experientiallabs": {
                "name": "ExperientialLabs [C7]",
                "options": {"apiKey": "{env:C7_EXPERIENTIAL_LABS_API}", "baseURL": "https://api.experientiallabs.ai/v1"},
                "models": {
                    "gpt-6-astra": {"name": "[1.0M] ExperientialLabs GPT-6 Astra", "context": 1048576}
                }
            },
            "nvidia_c9": {
                "name": "NVIDIA NIM [C9]",
                "options": {"apiKey": "{env:C9_NVIDIA_API}", "baseURL": "https://integrate.api.nvidia.com/v1"},
                "models": {
                    "moonshotai/kimi-k3": {"name": "Kimi K3", "context": 262144}
                }
            }
        }
    }
    fake_ssot.write_text(json.dumps(mock_data, indent=2), encoding="utf-8")

    code = (
        "import os, sys, json\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "import modules.tab_radar as tradar\n"
        f"tradar.OPENCODE_CONFIG = {repr(str(fake_ssot))}\n"
        "tab = tradar.TabRadar()\n"
        "tab.table_models_map = {\n"
        "    'gemini-3.7-flash': {\n"
        "        'id': 'gemini-3.7-flash', 'name': 'Gemini 3.7 Flash', 'provider': 'google',\n"
        "        'account_tag': 'C1', 'status': '200_OK', 'response_snippet': 'pong', 'context': 1048576\n"
        "    }\n"
        "}\n"
        "tab.table_checkboxes = {}\n"
        "tab.sync_to_opencode(silent=True)\n"
        "print('PASS')\n"
    )
    res = _run_isolated_code(code)
    assert res.returncode == 0, res.stderr

    result = json.loads(fake_ssot.read_text(encoding="utf-8"))
    providers = result.get("provider", {})
    assert "experientiallabs" in providers
    assert "gpt-6-astra" in providers["experientiallabs"]["models"]
    assert "nvidia_c9" in providers
    assert "moonshotai/kimi-k3" in providers["nvidia_c9"]["models"]
    assert "google" in providers
    assert "gemini-3.6-flash" in providers["google"]["models"]
    assert "gemini-3.7-flash" in providers["google"]["models"]
    assert "b_ai" not in providers
    assert "b_ai" in result.get("disabled_providers", [])


def test_radar_bai_explicitly_selected_and_verified_is_allowed(tmp_path):
    """Valida que b_ai se sincronice a opencode.jsonc SI el usuario lo marca explícitamente y tiene 200_OK coherente."""
    import json
    fake_ssot = tmp_path / "opencode_bai.jsonc"
    mock_data = {
        "$schema": "https://opencode.ai/config.json",
        "model": "google/gemini-3.7-flash",
        "small_model": "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "disabled_providers": ["alibaba", "bai", "b_ai"],
        "enabled_providers": ["google"],
        "provider": {
            "google": {
                "name": "Google AI Studio",
                "options": {"apiKey": "{env:C1_GEMINI_API}"},
                "models": {
                    "gemini-3.7-flash": {"name": "[1.0M] Gemini 3.7 Flash", "context": 1048576}
                }
            }
        }
    }
    fake_ssot.write_text(json.dumps(mock_data, indent=2), encoding="utf-8")

    code = (
        "import os, sys, json\n"
        "from PyQt6.QtWidgets import QApplication, QCheckBox\n"
        "app = QApplication([])\n"
        "import modules.tab_radar as tradar\n"
        f"tradar.OPENCODE_CONFIG = {repr(str(fake_ssot))}\n"
        "tab = tradar.TabRadar()\n"
        "tab.table_models_map = {\n"
        "    'minimax-m3': {\n"
        "        'id': 'minimax-m3', 'name': '[C7] B.AI MiniMax M3', 'provider': 'b_ai',\n"
        "        'account_tag': 'C7', 'status': '200_OK', 'response_snippet': 'hola mundo',\n"
        "        'latency_ms': 120, 'tokens': 10, 'tps': 25.0, 'context': 1048576\n"
        "    }\n"
        "}\n"
        "cb = QCheckBox()\n"
        "cb.setChecked(True)\n"
        "tab.table_checkboxes = {'minimax-m3': cb}\n"
        "groups = tab._build_provider_groups()\n"
        "assert ('b_ai', 'C7') in groups, f'Grupos no contiene b_ai: {groups}'\n"
        "tab.sync_to_opencode(silent=True)\n"
        "print('PASS')\n"
    )
    res = _run_isolated_code(code)
    assert res.returncode == 0, res.stderr
    assert "PASS" in res.stdout

    result = json.loads(fake_ssot.read_text(encoding="utf-8"))
    providers = result.get("provider", {})
    assert "b_ai" in providers, f"b_ai debe estar en providers: {providers.keys()}"
    assert "minimax-m3" in providers["b_ai"]["models"]
    assert "b_ai" in result.get("enabled_providers", [])
    assert "b_ai" not in result.get("disabled_providers", [])


def test_radar_defensive_sync_preserves_context_and_model_count_on_timeouts(tmp_path):
    """Valida que si un escaneo parcial trae menos modelos o sin context, el merge defensivo preserve modelos y contextos ricos del SSOT."""
    import json
    fake_ssot = tmp_path / "opencode_defensive.jsonc"
    mock_data = {
        "$schema": "https://opencode.ai/config.json",
        "model": "google/gemini-3.7-flash",
        "small_model": "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "disabled_providers": ["alibaba", "bai", "b_ai"],
        "enabled_providers": ["google", "nvidia_c9"],
        "provider": {
            "google": {
                "name": "Google AI Studio",
                "options": {"apiKey": "{env:C1_GEMINI_API}"},
                "models": {
                    "gemini-3.7-flash": {"name": "[1.0M] Gemini 3.7 Flash", "context": 1048576},
                    "gemini-3.6-flash": {"name": "[1.0M] Gemini 3.6 Flash", "context": 1048576}
                }
            },
            "nvidia_c9": {
                "name": "NVIDIA NIM [C9]",
                "options": {"apiKey": "{env:C9_NVIDIA_API}", "baseURL": "https://integrate.api.nvidia.com/v1"},
                "models": {
                    "moonshotai/kimi-k3": {"name": "Kimi K3", "context": 262144},
                    "deepseek-ai/deepseek-v4-flash-0731": {"name": "DeepSeek V4 Flash", "context": 262144},
                    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": {"name": "Nemotron Nano", "context": 256000}
                }
            }
        }
    }
    fake_ssot.write_text(json.dumps(mock_data, indent=2), encoding="utf-8")

    code = (
        "import os, sys, json\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "import modules.tab_radar as tradar\n"
        f"tradar.OPENCODE_CONFIG = {repr(str(fake_ssot))}\n"
        "tab = tradar.TabRadar()\n"
        "# Simular que nvidia_c9 solo tuvo 1 modelo 200_OK (los otros 2 sufrieron timeout)\n"
        "tab.table_models_map = {\n"
        "    'c9/moonshotai/kimi-k3': {\n"
        "        'id': 'c9/moonshotai/kimi-k3', 'name': 'Kimi K3', 'provider': 'nvidia',\n"
        "        'account_tag': 'C9', 'status': '200_OK', 'response_snippet': 'pong', 'context': 0\n"
        "    }\n"
        "}\n"
        "tab.table_checkboxes = {}\n"
        "tab.sync_to_opencode(silent=True)\n"
        "print('PASS')\n"
    )
    res = _run_isolated_code(code)
    assert res.returncode == 0, res.stderr
    assert "PASS" in res.stdout

    result = json.loads(fake_ssot.read_text(encoding="utf-8"))
    c9_models = result["provider"]["nvidia_c9"]["models"]
    # Debe haber preservado los 3 modelos originales de NVIDIA C9
    assert len(c9_models) == 3, f"Esperados 3 modelos en C9, obtenidos: {c9_models.keys()}"
    assert "deepseek-ai/deepseek-v4-flash-0731" in c9_models
    assert "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning" in c9_models
    # Y debe haber preservado el context de kimi-k3 aunque el nuevo venía con context: 0
    assert c9_models["moonshotai/kimi-k3"]["context"] == 262144