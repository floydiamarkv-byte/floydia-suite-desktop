"""
telemetry.py — Telemetría local SQLite (feature de roadmap).

Agrega en una única base local (WAL):
  - el Action Journal del Cleaner (action_journal.jsonl) por tipo/resultado,
  - los resultados de sondas del AI Radar (TTFT/TPS),
  - los checks de red de Diagnósticos.

Tablas: schema_version, action_journal, probe_results, diag_results.
Solo stdlib (sqlite3, json, os, time): cero dependencias nuevas.
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict

TELEMETRY_DB = os.environ.get(
    "FLOYDIA_TELEMETRY_DB",
    os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "floydia-suite",
        "telemetry.db",
    ),
)

_ACTION_DEFAULT_PATH = os.path.join(
    os.environ.get("FLOYDIA_WORKSPACE", os.getcwd()), "cache", "action_journal.jsonl"
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(TELEMETRY_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(TELEMETRY_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT OR IGNORE INTO schema_version(version) VALUES (1);
            CREATE TABLE IF NOT EXISTS action_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                module TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                result TEXT NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                detail TEXT
            );
            CREATE TABLE IF NOT EXISTS imported_action_keys (k TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS probe_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                provider TEXT,
                model TEXT,
                status TEXT,
                latency_ms INTEGER,
                ttft_ms INTEGER,
                tps REAL,
                tokens INTEGER,
                metric_mode TEXT
            );
            CREATE TABLE IF NOT EXISTS diag_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                key TEXT NOT NULL,
                alive INTEGER NOT NULL,
                lat TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_aj_ts ON action_journal(ts);
            CREATE INDEX IF NOT EXISTS idx_pr_ts ON probe_results(ts);
            """
        )


def ingest_action_journal(log_path: str = None) -> Dict[str, int]:
    """Lee action_journal.jsonl y sincroniza solo los registros nuevos a SQLite."""
    log_path = log_path or _ACTION_DEFAULT_PATH
    if not os.path.exists(log_path):
        return {"ingested": 0}
    init_db()
    inserted = 0
    with _connect() as conn:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.get("timestamp") or e.get("ts") or ""
                key = f"{ts}|{e.get('module', '')}|{e.get('action', '')}|{e.get('result', '')}|{e.get('target', '')}"
                if conn.execute("SELECT 1 FROM imported_action_keys WHERE k=?", (key,)).fetchone():
                    continue
                conn.execute(
                    "INSERT INTO action_journal(ts,module,action,target,result,duration_ms,detail) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        ts,
                        str(e.get("module", "")),
                        str(e.get("action", "")),
                        str(e.get("target", ""))[:400],
                        str(e.get("result", "")),
                        int(e.get("duration_ms", 0) or 0),
                        str(e.get("detail", ""))[:400],
                    ),
                )
                conn.execute("INSERT OR IGNORE INTO imported_action_keys(k) VALUES(?)", (key,))
                inserted += 1
    return {"ingested": inserted}


def record_probe_result(result: Dict[str, Any]) -> None:
    """Registra el resultado de un probe del AI Radar (TTFT/TPS/metría)."""
    try:
        init_db()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO probe_results(ts,provider,model,status,latency_ms,ttft_ms,tps,tokens,metric_mode) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    str(result.get("provider", "")),
                    str(result.get("id", "")),
                    str(result.get("status", "")),
                    result.get("latency_ms"),
                    result.get("ttft_ms"),
                    result.get("tps"),
                    result.get("tokens"),
                    result.get("metric_mode", "non_streaming"),
                ),
            )
    except Exception:
        pass  # la telemetría jamás debe romper la sonda


def record_diag(key: str, alive: bool, lat: str) -> None:
    try:
        init_db()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO diag_results(ts,key,alive,lat) VALUES(?,?,?,?)",
                (time.time(), key, 1 if alive else 0, lat),
            )
    except Exception:
        pass


def aggregate() -> Dict[str, Any]:
    """Resumen agregado para la UI: acciones por tipo/resultado, probes y checks recientes."""
    init_db()
    out: Dict[str, Any] = {}
    with _connect() as conn:
        try:
            out["total_actions"] = conn.execute("SELECT COUNT(*) FROM action_journal").fetchone()[0]
            out["ok_actions"] = conn.execute(
                "SELECT COUNT(*) FROM action_journal WHERE result='ok' OR result='SUCCESS'"
            ).fetchone()[0]
            out["by_result"] = dict(
                conn.execute("SELECT result, COUNT(*) c FROM action_journal GROUP BY result ORDER BY c DESC").fetchall()
            )
            out["by_action_top"] = conn.execute(
                "SELECT action, COUNT(*) c FROM action_journal GROUP BY action ORDER BY c DESC LIMIT 8"
            ).fetchall()
            out["recent_probes"] = conn.execute(
                "SELECT provider, model, status, latency_ms, ttft_ms, tps, metric_mode FROM probe_results "
                "ORDER BY ts DESC LIMIT 5"
            ).fetchall()
            out["diag_recent"] = conn.execute(
                "SELECT key, alive, lat FROM diag_results ORDER BY ts DESC LIMIT 8"
            ).fetchall()
        except sqlite3.Error:
            pass
    return out


def summarize_text() -> str:
    a = aggregate()
    lines = [
        "📊 TELEMETRÍA LOCAL (SQLite)",
        f"  • Acciones registradas (Action Journal): {a.get('total_actions', 0)}",
        f"  • Acciones OK: {a.get('ok_actions', 0)}",
    ]
    for r, c in a.get("by_result", {}).items():
        lines.append(f"      - {r}: {c}")
    top = a.get("by_action_top", [])
    if top:
        lines.append("  • Top acciones:")
        for act, c in top:
            lines.append(f"      - {act}: {c}")
    probes = a.get("recent_probes", [])
    if probes:
        lines.append("  • Últimas probes (AI Radar):")
        for prov, model, status, lat, ttft, tps, mode in probes:
            lines.append(f"      - {prov}/{model}: {status} | lat={lat}ms ttft={ttft}ms tps={tps} [{mode}]")
    diag = a.get("diag_recent", [])
    if diag:
        lines.append("  • Últimos checks de red:")
        for k, alive, lat in diag:
            lines.append(f"      - {k}: {'🟢' if alive else '🔴'} {lat}")
    lines.append(f"  (DB: {TELEMETRY_DB})")
    return "\n".join(lines)