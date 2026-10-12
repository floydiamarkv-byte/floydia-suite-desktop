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