"""Tests de modules.telemetry.py: ingestión del Action Journal, agregados y registro de sondas."""
import json
import os

from modules import telemetry as tel


def test_ingest_and_aggregate(tmp_path, monkeypatch):
    db = tmp_path / "telemetry.db"
    monkeypatch.setattr(tel, "TELEMETRY_DB", str(db))

    aj = tmp_path / "action_journal.jsonl"
    rows = [
        {"timestamp": "2026-09-03T00:00:00Z", "module": "tab_cleaner_bleachbit",
         "action": "vacuum", "target": "History", "result": "ok", "duration_ms": 12},
        {"timestamp": "2026-09-03T00:00:01Z", "module": "tab_cleaner_bleachbit",
         "action": "delete", "target": "cache/", "result": "ok", "duration_ms": 300},
        {"timestamp": "2026-09-03T00:00:02Z", "module": "tab_cleaner_bleachbit",
         "action": "delete", "target": "code cache/", "result": "error", "duration_ms": 5},
    ]
    aj.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    # idempotente: ingerir dos veces no duplica
    assert tel.ingest_action_journal(str(aj)) == {"ingested": 3}
    assert tel.ingest_action_journal(str(aj)) == {"ingested": 0}

    # registra sonda y check de red
    tel.record_probe_result({"provider": "deepseek", "id": "deepseek-chat", "status": "200_OK",
                             "latency_ms": 150, "ttft_ms": 40, "tps": 12.5, "tokens": 100,
                             "metric_mode": "streaming"})
    tel.record_diag("gateway", True, "2.3 ms")

    a = tel.aggregate()
    assert a["total_actions"] == 3
    assert a["ok_actions"] == 2
    assert a["by_result"].get("ok") == 2
    assert len(a["recent_probes"]) == 1
    assert a["recent_probes"][0][1] == "deepseek-chat"
    assert len(a["diag_recent"]) == 1

    summary = tel.summarize_text()
    assert "gateway" in summary and "🟢" in summary