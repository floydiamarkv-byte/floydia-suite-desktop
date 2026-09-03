#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Pestaña 5: Diagnóstico de Red & SRE Logs
Refactorizado con concurrencia ThreadPoolExecutor, lifecycle blindado y anti-colisión.
"""

import os
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QPlainTextEdit, QLineEdit
)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker,
    is_worker_running
)



def get_diag_targets() -> dict:
    return {
        "gateway": (os.environ.get("GATEWAY_NAME", "Gateway / Router"), os.environ.get("GATEWAY_IP", "192.168.1.1")),
        "server_1": (os.environ.get("SERVER1_NAME", "Homelab Node 1"), os.environ.get("SERVER1_IP", "192.168.1.238")),
        "server_2": (os.environ.get("SERVER2_NAME", "Homelab Node 2"), os.environ.get("SERVER2_IP", "192.168.1.232")),
        "internet": ("Google DNS (WAN)", os.environ.get("DNS_PRIMARY", "8.8.8.8"))
    }

def _probe_single_target(key: str, name: str, ip: str) -> tuple[str, dict]:
    """Ejecuta un probe ping individual de forma aislada y segura."""
    try:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5, shell=False)
        if p.returncode == 0:
            lat = "OK"
            for line in p.stdout.splitlines():
                if "time=" in line:
                    lat = line.split("time=")[1].split(" ")[0] + " ms"
                    break
            return key, {"name": name, "ip": ip, "lat": lat, "alive": True}
        else:
            return key, {"name": name, "ip": ip, "lat": "Timeout", "alive": False}
    except Exception as exc:
        return key, {"name": name, "ip": ip, "lat": "Error", "alive": False, "err": str(exc)}


class NetworkDiagWorker(CancellableThread):
    latencies_updated = pyqtSignal(dict)
    log_emitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True
        super().cancel()

    def is_cancelled(self) -> bool:
        return self._is_cancelled or super().is_cancelled()

    def run(self):
        if self.is_cancelled() or sys.is_finalizing():
            return

        targets = get_diag_targets()
        res = {}
        
        executor = None
        try:
            # Concurrencia real con ThreadPoolExecutor: probes en paralelo con protección de apagado
            executor = ThreadPoolExecutor(max_workers=4)
            future_to_key = {}
            for k, (name, ip) in targets.items():
                if self.is_cancelled() or sys.is_finalizing():
                    break
                try:
                    fut = executor.submit(_probe_single_target, k, name, ip)
                    future_to_key[fut] = k
                except RuntimeError:
                    # Protección explícita Python 3.14: cannot schedule new futures after interpreter shutdown
                    res[k] = {"name": name, "ip": ip, "lat": "Interrumpido", "alive": False}
                    break
                except Exception as exc:
                    res[k] = {"name": name, "ip": ip, "lat": "Error", "alive": False, "err": str(exc)}

            for future in as_completed(future_to_key):
                if self.is_cancelled() or sys.is_finalizing():
                    break
                try:
                    k, data = future.result()
                    res[k] = data
                except Exception:
                    key = future_to_key.get(future)
                    if key and key in targets:
                        name, ip = targets[key]
                        res[key] = {"name": name, "ip": ip, "lat": "Fallo", "alive": False}
        except (RuntimeError, SystemExit):
            return
        finally:
            if executor is not None:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass

        if not self.is_cancelled() and not sys.is_finalizing():
            try:
                self.latencies_updated.emit(res)
            except (RuntimeError, SystemExit):
                pass


class TabDiagnostics(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[NetworkDiagWorker] = None
        self.timer: Optional[QTimer] = None
        self.init_ui()
        self.start_diag_timer()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Encabezado
        title_box = QHBoxLayout()
        title = QLabel("📡 Diagnóstico de Red & Bitácora SRE")
        title.setFont(QFont("Inter", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        title_box.addWidget(title)
        
        self.btn_ping_now = QPushButton("⚡ Probar Conectividad Ahora")
        self.btn_ping_now.setObjectName("SecondaryBtn")
        self.btn_ping_now.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ping_now.clicked.connect(self.run_diag)
        title_box.addStretch()
        title_box.addWidget(self.btn_ping_now)
        layout.addLayout(title_box)

        # Grid de Latencias
        net_group = QFrame()
        net_group.setProperty("class", "CardFrame")
        net_lay = QVBoxLayout(net_group)
        net_lay.setContentsMargins(12, 12, 12, 12)

        net_title = QLabel("🌐 Latencias de Red en Tiempo Real (Probes Concurrentes)")
        net_title.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        net_lay.addWidget(net_title)

        self.grid_net = QGridLayout()
        self.grid_net.setSpacing(10)
        self.net_widgets = {}

        items = [
            ("router", "Router MikroTik", "192.168.1.1"),
            ("ct114", "Proxmox CT114", "192.168.1.238"),
            ("ct106", "Proxmox CT106", "192.168.1.232"),
            ("internet", "Google DNS (WAN)", "8.8.8.8"),
        ]

        row = 0
        col = 0
        for key, name, ip in items:
            card = QFrame()
            card.setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 8px;")
            c_lay = QVBoxLayout(card)
            c_lay.setSpacing(4)

            lbl_name = QLabel(f"{name} ({ip})")
            lbl_name.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            lbl_lat = QLabel("⏳ Midiendo...")
            lbl_lat.setFont(QFont("Inter", 12, QFont.Weight.Bold))

            c_lay.addWidget(lbl_name)
            c_lay.addWidget(lbl_lat)

            self.net_widgets[key] = {
                "card": card,
                "label": lbl_lat
            }

            self.grid_net.addWidget(card, row, col)
            col += 1
            if col > 1:
                col = 0
                row += 1

        net_lay.addLayout(self.grid_net)
        layout.addWidget(net_group)

        # Consola de Logs Global
        logs_group = QFrame()
        logs_group.setProperty("class", "CardFrame")
        logs_lay = QVBoxLayout(logs_group)
        logs_lay.setContentsMargins(12, 12, 12, 12)

        header_logs = QHBoxLayout()
        lbl_logs = QLabel("📋 Consola de Eventos & Logs en Vivo")
        lbl_logs.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        header_logs.addWidget(lbl_logs)

        btn_clear = QPushButton("Limpiar Consola")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.clicked.connect(lambda: self.log_console.clear())
        header_logs.addStretch()

        btn_telemetry = QPushButton("📊 Telemetría SQLite")
        btn_telemetry.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_telemetry.clicked.connect(self.show_telemetry)
        header_logs.addWidget(btn_telemetry)

        header_logs.addWidget(btn_clear)
        logs_lay.addLayout(header_logs)

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #070D14; border: 1px solid #1E3A5F; font-family: monospace; font-size: 11px;")
        self.log_console.setMaximumBlockCount(2000)
        logs_lay.addWidget(self.log_console)

        layout.addWidget(logs_group)

        self.log("✅ Pestaña de Diagnóstico de Red inicializada (Modo Concurrente Activo).")

    def log(self, text: str):
        self.log_console.appendPlainText(text)

    def show_telemetry(self):
        """Ingiere el Action Journal del Cleaner y muestra el resumen agregado en SQLite."""
        try:
            from modules import telemetry as fl_tel
            # El Action Journal vive en cache/ del workspace (mismo marker que tab_cleaner).
            import os as _os
            _ws = _os.environ.get("FLOYDIA_WORKSPACE", _os.getcwd())
            aj = _os.path.join(_ws, "cache", "action_journal.jsonl")
            ing = fl_tel.ingest_action_journal(aj)
            self.log(f"✅ Telemetría: {ing.get('ingested', 0)} registros nuevos ingeridos.")
            for line in fl_tel.summarize_text().splitlines():
                self.log(line)
        except Exception as exc:
            self.log(f"❌ Telemetría: {exc}")

    def start_diag_timer(self):
        self.run_diag()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_diag)
        self.timer.start(10000) # Cada 10s

    def run_diag(self):
        # Guardrail anti-colisión: si ya hay un worker corriendo, no solapar
        if self.worker is not None and self.worker.isRunning():
            return

        self.worker = NetworkDiagWorker()
        self.worker.latencies_updated.connect(self.on_latencies_updated)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def on_latencies_updated(self, results: dict):
        try:
            from modules import telemetry as fl_tel
        except Exception:
            fl_tel = None
        for k, info in results.items():
            if fl_tel is not None:
                fl_tel.record_diag(k, bool(info.get("alive")), str(info.get("lat", "")))
            if k in self.net_widgets:
                w = self.net_widgets[k]
                if info["alive"]:
                    w["label"].setText(f"🟢 {info['lat']}")
                    w["label"].setStyleSheet(f"color: {COLOR_SUCCESS};")
                    w["card"].setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_SUCCESS}; border-radius: 8px; padding: 8px;")
                else:
                    w["label"].setText(f"🔴 {info['lat']}")
                    w["label"].setStyleSheet(f"color: {COLOR_DANGER};")
                    w["card"].setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_DANGER}; border-radius: 8px; padding: 8px;")

    def cleanup(self):
        """Detiene timers y espera el worker de forma determinista y cooperativa sin terminate()."""
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.worker is not None:
            stop_worker(self.worker, timeout_ms=1800)
            if not is_worker_running(self.worker):
                self.worker = None

    def wait_for_shutdown(self, timeout_ms: int = 2000) -> bool:
        self.cleanup()
        if self.worker is not None and self.worker.isRunning():
            return self.worker.wait(timeout_ms)
        return True
