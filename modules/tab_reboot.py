#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Pestaña 1: Control de Infraestructura & Reboot Hub
Integración granular basada en SCRIPTS/restart_nodes_config.json y restart_workspace_engine.py
"""

import os
import sys
import json
import time
import subprocess
import fcntl
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread, QObject
from PyQt6.QtGui import QFont, QColor, QCursor, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QScrollArea, QFrame, QMessageBox, QProgressBar,
    QPlainTextEdit, QGridLayout, QSizePolicy, QDialog, QDialogButtonBox
)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker, is_worker_running
)

import socket
import subprocess

def find_workspace_root() -> str:
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.exists(os.path.join(curr, "SCRIPTS", "restart_workspace_engine.py")) or os.path.exists(os.path.join(curr, "SCRIPTS", "restart_nodes_config.json")):
            return curr
        curr = os.path.dirname(curr)
    # Segundo intento: buscar cualquier directorio padre que tenga SCRIPTS
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.isdir(os.path.join(curr, "SCRIPTS")):
            return curr
        curr = os.path.dirname(curr)
    # Fallback seguro: raíz del propio repo
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKSPACE_ROOT = os.environ.get("FLOYDIA_WORKSPACE", find_workspace_root())
SCRIPTS_DIR = os.path.join(WORKSPACE_ROOT, "SCRIPTS")
if os.path.exists(SCRIPTS_DIR) and SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

GLOBAL_SCRIPTS = os.environ.get("FLOYDIA_GLOBAL_SCRIPTS", os.path.join(WORKSPACE_ROOT, "SCRIPTS"))
if os.path.exists(GLOBAL_SCRIPTS) and GLOBAL_SCRIPTS not in sys.path:
    sys.path.insert(0, GLOBAL_SCRIPTS)

def get_config_file_path() -> str:
    safe_default = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "restart_nodes_config.json"
    )
    candidates = [
        os.path.join(SCRIPTS_DIR, "restart_nodes_config.json"),
        os.path.join(GLOBAL_SCRIPTS, "restart_nodes_config.json"),
        os.path.join(WORKSPACE_ROOT, "cache", "restart_nodes_config.json"),
        safe_default
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Primer arranque: usar SIEMPRE la ruta portable relativa al repo (candidato más seguro).
    return safe_default

CONFIG_FILE = get_config_file_path()

DEFAULT_NODES: List[Dict[str, Any]] = [
    {
        "id": "proxmox",
        "name": "Servidor Proxmox VE",
        "subtitle": "Host Proxmox & Contenedores LXC",
        "icon": "🖥️",
        "enabled": True,
        "order": 1,
        "type": "proxmox",
        "ip_env_key": "S01_PROXMOX_HOST",
        "default_ip": "192.168.1.220",
        "user_env_key": "S01_PROXMOX_USER",
        "default_user": "root",
        "pass_env_key": "S01_PROXMOX_PASS_MCP",
        "check_port": 8006,
        "timeout": 15,
        "warning": "⚠️ Afectará CT106 (Vault Obsidian) y CT114 (Servidor Híbrido). Se recomienda verificar antes de reiniciar."
    },
    {
        "id": "hp45",
        "name": "Laptop HP45 (Secundaria)",
        "subtitle": "Debian / MX Linux",
        "icon": "💻",
        "enabled": True,
        "order": 2,
        "type": "ssh_linux",
        "ip_env_key": "S25_HP45_IP",
        "default_ip": "192.168.1.204",
        "user_env_key": "S25_HP45_USER",
        "default_user": "tec",
        "pass_env_key": "S25_HP45_PASS",
        "check_port": 22,
        "timeout": 10,
        "warning": None
    },
    {
        "id": "mikrotik_ap",
        "name": "MikroTik AP (RB941)",
        "subtitle": "Punto de Acceso WiFi MikroTik",
        "icon": "📡",
        "enabled": True,
        "order": 3,
        "type": "mikrotik",
        "ip_env_key": "S19_MIKROTIK_RB941_IP",
        "default_ip": "192.168.1.115",
        "user_env_key": "S19_MIKROTIK_RB941_USER",
        "default_user": "admin",
        "pass_env_key": "S19_MIKROTIK_RB941_PASS",
        "check_port": 22,
        "timeout": 8,
        "warning": None
    },
    {
        "id": "tplink_ap",
        "name": "TP-Link AP",
        "subtitle": "Punto de Acceso WiFi TP-Link",
        "icon": "📶",
        "enabled": False,
        "order": 4,
        "type": "tplink",
        "ip_env_key": "S20_TPLINK_AP_IP",
        "default_ip": "192.168.1.210",
        "user_env_key": "S20_TPLINK_AP_USER",
        "default_user": "admin",
        "pass_env_key": "S20_TPLINK_AP_PASS",
        "check_port": 22,
        "timeout": 8,
        "warning": None
    },
    {
        "id": "mikrotik_router",
        "name": "MikroTik Router (RB750Gr3)",
        "subtitle": "Router Central de Red (Gateway 192.168.1.1)",
        "icon": "🌐",
        "enabled": False,
        "order": 5,
        "type": "mikrotik",
        "ip_env_key": "S19_MIKROTIK_RB750GR3_IP",
        "default_ip": "192.168.1.1",
        "user_env_key": "S19_MIKROTIK_RB750GR3_USER",
        "default_user": "admin",
        "pass_env_key": "S19_MIKROTIK_RB750GR3_PASS",
        "check_port": 22,
        "timeout": 10,
        "warning": "⚠️ Cortará la conectividad de toda la red durante su reinicio."
    },
    {
        "id": "hp15",
        "name": "Laptop HP15 (Local)",
        "subtitle": "Estación Principal Debian (Host Ejecutor)",
        "icon": "⚡",
        "enabled": False,
        "order": 6,
        "type": "localhost",
        "ip_env_key": "HP15_IP",
        "default_ip": "127.0.0.1",
        "user_env_key": "USER",
        "default_user": "tec",
        "pass_env_key": None,
        "check_port": None,
        "timeout": 15,
        "warning": "🚨 Se ejecutará de ÚLTIMO con cuenta regresiva cancelable de 10 segundos."
    }
]

class DefaultRebootEngine:
    @staticmethod
    def load_env_safely():
        env_candidates = [
            os.path.join(WORKSPACE_ROOT, ".env"),
            os.path.expanduser("~/.config/floydia-suite/.env"),
            os.path.expanduser("~/.config/floydia-suite/secrets.env"),
            os.path.expanduser("~/.secrets/antigravity.env")
        ]
        res = {}
        for env_p in env_candidates:
            if os.path.exists(env_p):
                try:
                    with open(env_p, "r", encoding="utf-8") as f:
                        for line in f:
                            s = line.strip()
                            if s and not s.startswith("#") and "=" in s:
                                p = s.split("=", 1)
                                k = p[0].strip()
                                v = p[1].strip().strip('"').strip("'")
                                if k not in res:
                                    res[k] = v
                except Exception:
                    pass
        return res

    @staticmethod
    def get_resolved_node(node, env_map):
        resolved = dict(node)
        ip_k = node.get("ip_env_key")
        resolved["ip"] = env_map.get(ip_k, node.get("default_ip", "127.0.0.1")) if ip_k else node.get("default_ip", "127.0.0.1")
        user_k = node.get("user_env_key")
        resolved["user"] = env_map.get(user_k, node.get("default_user", "root")) if user_k else node.get("default_user", "root")
        pass_k = node.get("pass_env_key")
        resolved["password"] = env_map.get(pass_k, "") if pass_k else ""
        return resolved

    @staticmethod
    def ping_host_fast(ip, timeout=1.0):
        try:
            cmd = ["ping", "-c", "1", "-W", "1", str(ip)]
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 0.5)
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def check_node_health(node, env_map):
        resolved = DefaultRebootEngine.get_resolved_node(node, env_map)
        ip = resolved.get("ip", "127.0.0.1")
        if ip in ["127.0.0.1", "localhost"]:
            return {"ping_ok": True, "latency_ms": 0.1, "port_ok": True, "status": "ONLINE", "ip": ip}
        try:
            t0 = time.perf_counter()
            r = subprocess.run(["ping", "-c", "1", "-W", "1", str(ip)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2.0)
            lat = round((time.perf_counter() - t0) * 1000, 1)
            ok = (r.returncode == 0)
            return {"ping_ok": ok, "latency_ms": lat if ok else 0, "port_ok": True, "status": "ONLINE" if ok else "OFFLINE", "ip": ip}
        except Exception:
            return {"ping_ok": False, "latency_ms": 0, "port_ok": False, "status": "OFFLINE", "ip": ip}

    @staticmethod
    def execute_reboot_node(node, env_map, dry_run=False, log_cb=None):
        if log_cb:
            log_cb(f"⚠️ ERROR: restart_workspace_engine no disponible en el path para: {node.get('name')}", "ERROR")
        return False, "Motor real de reinicio no disponible"

# Importar el motor de reinicio real desde SCRIPTS
SCRIPTS_DIR = os.path.join(WORKSPACE_ROOT, "SCRIPTS")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

try:
    import restart_workspace_engine as engine
except ImportError:
    try:
        from modules import restart_workspace_engine as engine
    except ImportError:
        engine = DefaultRebootEngine()


from modules.state_store import atomic_write_json as atomic_json_write

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED
)


class WorkerSignals(QObject):
    log = pyqtSignal(str, str)  # mensaje, nivel (INFO, SUCCESS, WARN, ERROR)
    node_status = pyqtSignal(str, str, str)  # node_id, status_code, extra_text
    health_result = pyqtSignal(str, dict)
    finished = pyqtSignal(bool, str)
    countdown_tick = pyqtSignal(int)
    progress_val = pyqtSignal(int)


class HealthCheckWorker(QThread):
    def __init__(self, nodes: List[Dict[str, Any]], env_map: Dict[str, str]):
        super().__init__()
        self.nodes = list(nodes)
        self.env_map = dict(env_map)
        self.signals = WorkerSignals()
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        self.signals.log.emit("🔍 Iniciando Pre-Flight Health Check en todos los nodos...", "INFO")
        for n in self.nodes:
            if self._cancel_event.is_set() or self.isInterruptionRequested():
                self.signals.finished.emit(False, "Health check cancelado")
                return

            try:
                res = engine.check_node_health(n, self.env_map)
                self.signals.health_result.emit(n["id"], res)
                status_color = "SUCCESS" if res.get("ping_ok") else "ERROR"
                lat_str = f"{res.get('latency_ms', 0)}ms" if res.get("ping_ok") else "OFFLINE"
                self.signals.log.emit(f"Nodo {n['name']} ({res.get('ip', n.get('default_ip'))}): {res.get('status', 'OFFLINE')} [{lat_str}]", status_color)
            except Exception as exc:
                self.signals.log.emit(f"❌ Error verificando {n.get('name')}: {exc}", "ERROR")
            time.sleep(0.04)

        if not self._cancel_event.is_set() and not self.isInterruptionRequested():
            self.signals.log.emit("✅ Pre-Flight Health Check finalizado.", "SUCCESS")
            self.signals.finished.emit(True, "Health check terminado")


class RebootSequenceWorker(QThread):
    def __init__(self, active_nodes: List[Dict[str, Any]], env_map: Dict[str, str], dry_run: bool = False):
        super().__init__()
        self.active_nodes = list(active_nodes)
        self.env_map = dict(env_map)
        self.dry_run = dry_run
        self.signals = WorkerSignals()
        self._cancel_event = threading.Event()
        self.is_cancelled = False

    def cancel(self):
        self._cancel_event.set()
        self.is_cancelled = True

    def run(self):
        mode_str = "[MODO SIMULACIÓN DRY-RUN]" if self.dry_run else "[MODO REAL DE PRODUCCIÓN]"
        total_nodes = len(self.active_nodes)
        self.signals.log.emit(f"🚀 Iniciando secuencia de reinicio {mode_str} para {total_nodes} nodos seleccionados...", "WARN")

        for idx, node in enumerate(self.active_nodes, 1):
            if self.is_cancelled:
                self.signals.log.emit("🛑 Secuencia de reinicio cancelada por el usuario.", "ERROR")
                self.signals.finished.emit(False, "Secuencia abortada por el usuario")
                return

            n_id = node["id"]
            n_name = node["name"]
            n_type = node.get("type", "ssh_linux")

            self.signals.node_status.emit(n_id, "RUNNING", "Reiniciando...")
            self.signals.log.emit(f"Paso {idx}/{total_nodes}: Procesando {n_name} ({node.get('default_ip')})...", "INFO")
            self.signals.progress_val.emit(int(((idx - 1) / total_nodes) * 100))

            # Manejo especial para HP15 (Localhost)
            if n_type == "localhost":
                self.signals.log.emit("🚨 Nodo final HP15 alcanzado. Iniciando cuenta regresiva de 10s cancelable...", "WARN")
                for c in range(10, 0, -1):
                    if self.is_cancelled:
                        self.signals.log.emit("🛑 Reinicio de HP15 cancelado a tiempo.", "SUCCESS")
                        self.signals.node_status.emit(n_id, "SKIPPED", "Cancelado")
                        self.signals.finished.emit(True, "Finalizado (HP15 omitido)")
                        return
                    self.signals.countdown_tick.emit(c)
                    self.signals.log.emit(f"⏳ HP15 reiniciará en {c} segundos...", "WARN")
                    time.sleep(1)

            def log_cb(msg: str, lvl: str):
                self.signals.log.emit(msg, lvl)

            try:
                ok, detail = engine.execute_reboot_node(node, self.env_map, dry_run=self.dry_run, log_cb=log_cb)
            except Exception as e_node:
                ok, detail = False, f"Excepción durante reinicio: {e_node}"

            if ok:
                self.signals.node_status.emit(n_id, "SUCCESS", "Reiniciado OK")
                self.signals.log.emit(f"✅ {n_name} completado con éxito.", "SUCCESS")
            else:
                self.signals.node_status.emit(n_id, "ERROR", "Fallo")
                self.signals.log.emit(f"❌ Error en {n_name}: {detail}", "ERROR")

            self.signals.progress_val.emit(int((idx / total_nodes) * 100))
            time.sleep(0.8)

        self.signals.finished.emit(True, "Secuencia de reinicio completada exitosamente.")


class NodeCardWidget(QFrame):
    order_changed = pyqtSignal(str, str)  # node_id, "up"|"down"
    toggle_changed = pyqtSignal(str, bool)

    def __init__(self, node: Dict[str, Any], env_map: Dict[str, str], parent=None):
        super().__init__(parent)
        self.node = node
        self.env_map = env_map
        self.setObjectName("NodeCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # 1. Badge de Orden
        self.lbl_order = QLabel(f"#{node.get('order', 1)}")
        self.lbl_order.setStyleSheet("font-weight: 800; font-size: 13px; color: #10D2AD; min-width: 26px;")
        self.lbl_order.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_order)

        # 2. Checkbox Habilitar
        self.chk_enable = QCheckBox()
        self.chk_enable.setChecked(node.get("enabled", True))
        self.chk_enable.toggled.connect(lambda v: self.toggle_changed.emit(self.node["id"], v))
        self.chk_enable.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.chk_enable)

        # 3. Icono
        lbl_icon = QLabel(node.get("icon", "🖥️"))
        lbl_icon.setStyleSheet("font-size: 22px; background: transparent;")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_icon)

        # 4. Información del Nodo
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        resolved = engine.get_resolved_node(node, env_map)
        ip = resolved["ip"]
        port = node.get("check_port")
        port_str = f" · Port: {port}" if port else ""

        self.lbl_title = QLabel(node["name"])
        self.lbl_title.setStyleSheet("font-weight: 700; font-size: 13px; color: #F5F8F7;")
        
        sub_text = f"{node.get('subtitle', '')} [{ip}{port_str}]"
        self.lbl_sub = QLabel(sub_text)
        self.lbl_sub.setStyleSheet("font-size: 11px; color: #94A3B8;")

        info_layout.addWidget(self.lbl_title)
        info_layout.addWidget(self.lbl_sub)
        
        if node.get("warning"):
            lbl_warn = QLabel(node["warning"])
            lbl_warn.setStyleSheet("font-size: 10px; color: #F59E0B; font-weight: 600;")
            info_layout.addWidget(lbl_warn)

        layout.addLayout(info_layout, stretch=1)

        # 5. Badge de Latencia / Ping
        self.lbl_ping = QLabel("⚪ Sin probar")
        self.lbl_ping.setStyleSheet("background-color: #1F364D; color: #94A3B8; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 3px 6px;")
        layout.addWidget(self.lbl_ping)

        # 6. Badge de Estado de Ejecución
        self.lbl_status = QLabel("⚪ PENDIENTE")
        self.lbl_status.setStyleSheet("background-color: #1F364D; color: #CBD5E1; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 4px 8px;")
        layout.addWidget(self.lbl_status)

        # 7. Botones de Reordenamiento
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(2)

        self.btn_up = QPushButton("▲")
        self.btn_up.setObjectName("ArrowBtn")
        self.btn_up.setFixedSize(24, 20)
        self.btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_up.clicked.connect(lambda: self.order_changed.emit(self.node["id"], "up"))

        self.btn_down = QPushButton("▼")
        self.btn_down.setObjectName("ArrowBtn")
        self.btn_down.setFixedSize(24, 20)
        self.btn_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_down.clicked.connect(lambda: self.order_changed.emit(self.node["id"], "down"))

        btn_layout.addWidget(self.btn_up)
        btn_layout.addWidget(self.btn_down)
        layout.addLayout(btn_layout)

    def set_order_label(self, order_num: int):
        self.lbl_order.setText(f"#{order_num}")

    def update_ping_result(self, res: dict):
        if res.get("ping_ok"):
            lat = res.get("latency_ms", 0)
            self.lbl_ping.setText(f"🟢 {lat}ms")
            self.lbl_ping.setStyleSheet("background-color: #064E3B; color: #10D2AD; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 3px 6px;")
        else:
            self.lbl_ping.setText("🔴 OFFLINE")
            self.lbl_ping.setStyleSheet("background-color: #7F1D1D; color: #F87171; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 3px 6px;")

    def set_execution_status(self, code: str, text: str):
        if code == "RUNNING":
            self.lbl_status.setText(f"🟡 {text.upper()}")
            self.lbl_status.setStyleSheet("background-color: #78350F; color: #FBBF24; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 4px 8px;")
        elif code == "SUCCESS":
            self.lbl_status.setText(f"🟢 {text.upper()}")
            self.lbl_status.setStyleSheet("background-color: #064E3B; color: #10D2AD; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 4px 8px;")
        elif code == "ERROR":
            self.lbl_status.setText(f"🔴 {text.upper()}")
            self.lbl_status.setStyleSheet("background-color: #7F1D1D; color: #EF4444; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 4px 8px;")
        elif code == "SKIPPED":
            self.lbl_status.setText(f"⏭️ {text.upper()}")
            self.lbl_status.setStyleSheet("background-color: #334155; color: #94A3B8; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 4px 8px;")
        else:
            self.lbl_status.setText(f"⚪ {text.upper()}")
            self.lbl_status.setStyleSheet("background-color: #1F364D; color: #CBD5E1; font-size: 10px; font-weight: 700; border-radius: 4px; padding: 4px 8px;")


class TabReboot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.env_map = engine.load_env_safely()
        self.nodes = self.load_nodes_config()
        self.card_widgets: Dict[str, NodeCardWidget] = {}
        self.worker: Optional[QThread] = None

        self.init_ui()
        self.start_periodic_health_check()

    def load_nodes_config(self) -> List[Dict[str, Any]]:
        candidates = [
            CONFIG_FILE,
            os.path.join(SCRIPTS_DIR, "restart_nodes_config.json"),
            os.path.join(GLOBAL_SCRIPTS, "restart_nodes_config.json"),
            os.path.join(WORKSPACE_ROOT, "cache", "restart_nodes_config.json")
        ]
        for cfg_path in candidates:
            if cfg_path and os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and len(data) > 0:
                            return sorted(data, key=lambda x: x.get("order", 99))
                except Exception as e:
                    print(f"[ERROR] No se pudo leer {cfg_path}: {e}")
        return [dict(n) for n in DEFAULT_NODES]

    def save_nodes_config(self):
        for idx, n in enumerate(self.nodes, 1):
            n["order"] = idx
        try:
            atomic_json_write(CONFIG_FILE, self.nodes)
        except Exception as e:
            self.log_message(f"Error al guardar configuración: {e}", "ERROR")

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # 1. ENCABEZADO Y ACCIONES RÁPIDAS DE SELECCIÓN
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Orquestador de Reinicio de Infraestructura & Nodos")
        title.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        
        subtitle = QLabel("Control granular de Servidores Proxmox, Routers MikroTik, Laptops y Host Local HP15")
        subtitle.setFont(QFont("Inter", 10))
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_bar.addLayout(title_box)
        top_bar.addStretch()

        self.btn_health = QPushButton("Comprobar Conectividad")
        self.btn_health.setObjectName("SecondaryBtn")
        self.btn_health.setCursor(Qt.CursorShape.PointingHandCursor)
        icon_refresh = Path(__file__).resolve().parent.parent / "assets" / "icons" / "btn_refresh.svg"
        if icon_refresh.exists():
            self.btn_health.setIcon(QIcon(str(icon_refresh)))
            self.btn_health.setIconSize(QSize(15, 15))
        self.btn_health.clicked.connect(self.run_health_check)
        top_bar.addWidget(self.btn_health)

        layout.addLayout(top_bar)

        # 2. BARRA DE SELECCIÓN RÁPIDA DE NODOS
        sel_bar = QHBoxLayout()
        sel_label = QLabel("Selección rápida:")
        sel_label.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        sel_bar.addWidget(sel_label)

        btn_sel_all = QPushButton("Seleccionar Todos")
        btn_sel_all.setObjectName("SecondaryBtn")
        btn_sel_all.clicked.connect(self.select_all_nodes)
        sel_bar.addWidget(btn_sel_all)

        btn_sel_infra = QPushButton("Solo Infraestructura")
        btn_sel_infra.setObjectName("SecondaryBtn")
        btn_sel_infra.clicked.connect(self.select_infra_only)
        sel_bar.addWidget(btn_sel_infra)

        btn_desel_all = QPushButton("Deseleccionar Todos")
        btn_desel_all.setObjectName("SecondaryBtn")
        btn_desel_all.clicked.connect(self.deselect_all_nodes)
        sel_bar.addWidget(btn_desel_all)

        sel_bar.addStretch()
        layout.addLayout(sel_bar)

        # 3. LISTA DE TARJETAS DE NODOS (SCROLLABLE)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        self.nodes_vbox = QVBoxLayout(container)
        self.nodes_vbox.setContentsMargins(0, 0, 0, 0)
        self.nodes_vbox.setSpacing(8)

        self.render_node_cards()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # 4. BARRA DE PROGRESO Y CONTROLES DE EJECUCIÓN
        exec_group = QFrame()
        exec_group.setProperty("class", "CardFrame")
        exec_lay = QVBoxLayout(exec_group)
        exec_lay.setContentsMargins(12, 10, 12, 10)
        exec_lay.setSpacing(8)

        prog_row = QHBoxLayout()
        self.lbl_progress = QLabel("Estado: Listo para ejecutar")
        self.lbl_progress.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.lbl_progress.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        prog_row.addWidget(self.lbl_progress)
        prog_row.addStretch()

        self.lbl_countdown = QLabel("")
        self.lbl_countdown.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.lbl_countdown.setStyleSheet("color: #EF4444;")
        prog_row.addWidget(self.lbl_countdown)
        exec_lay.addLayout(prog_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        exec_lay.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.chk_dry_run = QCheckBox("Simulación Dry-Run (Sin ejecutar reinicio real)")
        self.chk_dry_run.setStyleSheet("font-size: 11px; color: #38BDF8;")
        btn_row.addWidget(self.chk_dry_run)
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Cancelar Secuencia")
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.setEnabled(False)
        icon_kill = Path(__file__).resolve().parent.parent / "assets" / "icons" / "btn_kill.svg"
        if icon_kill.exists():
            self.btn_cancel.setIcon(QIcon(str(icon_kill)))
            self.btn_cancel.setIconSize(QSize(15, 15))
        self.btn_cancel.clicked.connect(self.cancel_execution)
        btn_row.addWidget(self.btn_cancel)

        self.btn_start = QPushButton("Ejecutar Reinicio Secuencial de Nodos Seleccionados")
        self.btn_start.setObjectName("PrimaryBtn")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        icon_rocket = Path(__file__).resolve().parent.parent / "assets" / "icons" / "btn_rocket.svg"
        if icon_rocket.exists():
            self.btn_start.setIcon(QIcon(str(icon_rocket)))
            self.btn_start.setIconSize(QSize(16, 16))
        self.btn_start.clicked.connect(self.confirm_and_start_reboot)
        btn_row.addWidget(self.btn_start)

        exec_lay.addLayout(btn_row)
        layout.addWidget(exec_group)

        # 5. CONSOLA DE LOGS
        log_title = QLabel("Bitácora de Eventos & Salida en Tiempo Real")
        log_title.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        layout.addWidget(log_title)

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("background-color: #070D14; border: 1px solid #1E3A5F; font-family: monospace; font-size: 11px;")
        self.log_console.setMaximumHeight(120)
        self.log_console.setMaximumBlockCount(2000)
        layout.addWidget(self.log_console)

        self.log_message("Pestaña Reboot inicializada. Configuración de 6 nodos cargada desde restart_nodes_config.json.", "SUCCESS")

    def render_node_cards(self):
        while self.nodes_vbox.count():
            item = self.nodes_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                self.nodes_vbox.removeItem(item)

        self.card_widgets.clear()
        for idx, node in enumerate(self.nodes, 1):
            node["order"] = idx
            card = NodeCardWidget(node, self.env_map)
            card.order_changed.connect(self.handle_order_change)
            card.toggle_changed.connect(self.handle_toggle_change)
            self.card_widgets[node["id"]] = card
            self.nodes_vbox.addWidget(card)

        self.nodes_vbox.addStretch()

    def handle_order_change(self, node_id: str, direction: str):
        idx = next((i for i, n in enumerate(self.nodes) if n["id"] == node_id), -1)
        if idx == -1:
            return

        if direction == "up" and idx > 0:
            self.nodes[idx], self.nodes[idx - 1] = self.nodes[idx - 1], self.nodes[idx]
        elif direction == "down" and idx < len(self.nodes) - 1:
            self.nodes[idx], self.nodes[idx + 1] = self.nodes[idx + 1], self.nodes[idx]
        else:
            return

        self.save_nodes_config()
        self.render_node_cards()

    def handle_toggle_change(self, node_id: str, enabled: bool):
        for n in self.nodes:
            if n["id"] == node_id:
                n["enabled"] = enabled
                break
        self.save_nodes_config()

    def select_all_nodes(self):
        for card in self.card_widgets.values():
            card.chk_enable.setChecked(True)

    def select_infra_only(self):
        for node_id, card in self.card_widgets.items():
            if node_id == "hp15":
                card.chk_enable.setChecked(False)
            else:
                card.chk_enable.setChecked(True)

    def deselect_all_nodes(self):
        for card in self.card_widgets.values():
            card.chk_enable.setChecked(False)

    def log_message(self, msg: str, level: str = "INFO"):
        prefix = "ℹ️"
        if level == "SUCCESS": prefix = "✅"
        elif level == "WARN": prefix = "⚠️"
        elif level == "ERROR": prefix = "❌"
        self.log_console.appendPlainText(f"{prefix} {msg}")

    def run_health_check(self):
        if self.worker and self.worker.isRunning():
            return
        self.btn_health.setEnabled(False)
        self.worker = HealthCheckWorker(self.nodes, self.env_map)
        self.worker.signals.log.connect(self.log_message)
        self.worker.signals.health_result.connect(self.handle_health_result)
        self.worker.signals.finished.connect(lambda: self.btn_health.setEnabled(True))
        self.worker.start()

    def handle_health_result(self, node_id: str, res: dict):
        if node_id in self.card_widgets:
            self.card_widgets[node_id].update_ping_result(res)

    def start_periodic_health_check(self):
        QTimer.singleShot(1000, self.run_health_check)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_health_check)
        self.timer.start(25000)

    def confirm_and_start_reboot(self):
        try:
            active_nodes = [n for n in self.nodes if n.get("enabled", True)]
            if not active_nodes:
                box = QMessageBox(self)
                box.setWindowTitle("FloydIA Suite — Sin Nodos")
                box.setIcon(QMessageBox.Icon.Warning)
                box.setText("<b style='color: #F87171; font-size: 13px;'>No hay nodos seleccionados</b>")
                box.setInformativeText("<span style='color: #E2E8F0;'>Debes marcar la casilla de al menos un nodo en la lista superior para ejecutar el reinicio.</span>")
                box.addButton("Entendido", QMessageBox.ButtonRole.AcceptRole)
                box.exec()
                return

            # B-12 (GLM): Validar previamente si hay un health-check o worker activo para no descartar silenciosamente
            if (self.worker and self.worker.isRunning()) or (self.health_worker and self.health_worker.isRunning()):
                QMessageBox.warning(
                    self, "Operación en Curso",
                    "Hay una verificación de salud o secuencia activa en este momento. Espera a que concluya antes de iniciar el reinicio."
                )
                return

            is_dry = self.chk_dry_run.isChecked()
            has_hp15 = any("hp15" in str(n.get("id", "")).lower() or "hp15" in str(n.get("name", "")).lower() for n in active_nodes)

            nodes_list_html = "".join([
                f"<li style='color: #F1F5F9; margin-bottom: 3px;'><b>{n.get('name')}</b> <span style='color: #38BDF8;'>({n.get('default_ip')})</span></li>"
                for n in active_nodes
            ])

            if is_dry:
                mode_badge = (
                    "<div style='background-color: #064E3B; border: 1px solid #10B981; "
                    "color: #34D399; padding: 6px 10px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>"
                    "● MODO SEGURO: SIMULACIÓN (Dry-Run — No ejecutará reinicios reales)"
                    "</div>"
                )
                action_btn_text = "▶ Ejecutar Simulación"
            else:
                mode_badge = (
                    "<div style='background-color: #7F1D1D; border: 1px solid #EF4444; "
                    "color: #FCA5A5; padding: 6px 10px; border-radius: 6px; font-weight: bold; margin-bottom: 8px;'>"
                    "● MODO PRODUCCIÓN: REINICIO FÍSICO Y REAL DE SERVIDORES"
                    "</div>"
                )
                action_btn_text = "Confirmar Reinicio en Producción"

            hp15_warning = ""
            if has_hp15:
                hp15_warning = (
                    "<div style='background-color: #3B1212; border: 1px solid #F87171; color: #FECACA; "
                    "padding: 8px 10px; border-radius: 6px; margin-top: 10px; font-size: 11px;'>"
                    "<b>[ALERTA CRÍTICA]:</b> El host HP15 Local está incluido. "
                    "Al finalizar la secuencia se disparará el reinicio físico del host tras 10s de cuenta regresiva."
                    "</div>"
                )

            info_html = (
                f"{mode_badge}"
                f"<div style='background-color: #0E1726; border: 1px solid #1E2E44; border-radius: 6px; padding: 8px 12px; margin-top: 6px;'>"
                f"<span style='color: #94A3B8; font-weight: bold; font-size: 11px;'>Nodos Seleccionados ({len(active_nodes)}):</span>"
                f"<ul style='margin: 4px 0 2px 18px; padding: 0;'>"
                f"{nodes_list_html}"
                f"</ul>"
                f"</div>"
                f"{hp15_warning}"
            )

            box = QMessageBox(self)
            box.setWindowTitle("Confirmación de Secuencia de Reinicio — FloydIA Suite")
            
            # Cargar icono de advertencia nítido desde assets
            icon_asset = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
            if icon_asset.exists():
                pix = QPixmap(str(icon_asset)).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                box.setIconPixmap(pix)
            else:
                box.setIcon(QMessageBox.Icon.Warning if not is_dry else QMessageBox.Icon.Information)

            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText("<h3 style='color: #00F5D4; margin: 0 0 6px 0;'>¿Confirmar ejecución de la secuencia?</h3>")
            box.setInformativeText(info_html)

            btn_confirm = box.addButton(action_btn_text, QMessageBox.ButtonRole.AcceptRole)
            btn_cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_cancel)

            if not is_dry:
                btn_confirm.setStyleSheet("background-color: #DC2626; color: #FFFFFF; font-weight: bold; border: 1px solid #EF4444; border-radius: 6px; padding: 8px 16px;")
            else:
                btn_confirm.setStyleSheet("background-color: #059669; color: #FFFFFF; font-weight: bold; border: 1px solid #10B981; border-radius: 6px; padding: 8px 16px;")

            box.exec()

            if box.clickedButton() == btn_confirm:
                self.start_reboot_sequence(active_nodes, is_dry)
        except Exception as exc:
            self.log_message(f"Error al iniciar diálogo de confirmación: {exc}", "ERROR")
            QMessageBox.critical(self, "Error", f"Ocurrió un error al preparar el reinicio:\n{exc}")

    def start_reboot_sequence(self, active_nodes: List[Dict[str, Any]], dry_run: bool):
        if self.worker and self.worker.isRunning():
            return

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_health.setEnabled(False)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("Ejecutando secuencia de reinicio...")

        for card in self.card_widgets.values():
            card.set_execution_status("PENDING", "Pendiente")

        self.worker = RebootSequenceWorker(active_nodes, self.env_map, dry_run=dry_run)
        self.worker.signals.log.connect(self.log_message)
        self.worker.signals.node_status.connect(self.handle_node_status)
        self.worker.signals.countdown_tick.connect(self.handle_countdown)
        self.worker.signals.progress_val.connect(self.progress_bar.setValue)
        self.worker.signals.finished.connect(self.handle_reboot_finished)
        self.worker.start()

    def handle_node_status(self, node_id: str, status_code: str, text: str):
        if node_id in self.card_widgets:
            self.card_widgets[node_id].set_execution_status(status_code, text)

    def handle_countdown(self, seconds: int):
        self.lbl_countdown.setText(f"🚨 REINICIO LOCAL HP15 EN: {seconds}s")

    def cancel_execution(self):
        if self.worker and isinstance(self.worker, RebootSequenceWorker):
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.log_message("Cancelación solicitada al worker...", "WARN")

    def handle_reboot_finished(self, success: bool, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_health.setEnabled(True)
        self.lbl_countdown.setText("")
        self.lbl_progress.setText(f"Estado: {msg}")
        self.progress_bar.setValue(100 if success else 0)
        if success:
            QMessageBox.information(self, "Secuencia Finalizada", f"✅ {msg}")
        else:
            QMessageBox.warning(self, "Secuencia Detenida", f"⚠️ {msg}")

    def cleanup(self):
        """Detiene timers y espera el worker de forma determinista y cooperativa sin terminate()."""
        if hasattr(self, "timer") and self.timer is not None:
            self.timer.stop()
            self.timer = None
        if self.worker is not None:
            stop_worker(self.worker, timeout_ms=1800)
            self.worker = None

    def wait_for_shutdown(self, timeout_ms: int = 2000) -> bool:
        """Contrato FSU-002: verificación pasiva de que el worker activo terminó."""
        if self.worker is None:
            return True
        try:
            return not is_worker_running(self.worker)
        except RuntimeError:
            # El objeto C++ subyacente ya fue destruido: worker terminado.
            return True

