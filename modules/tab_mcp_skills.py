#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Pestaña 3: MCP Cockpit & Skills Studio
Gestión granular de servidores MCP (~/.gemini/config/mcp_config.json) y activación/desactivación de Skills.
Refactorizado con sincronización asíncrona de Skills (SkillSyncWorker), debounce de 150ms en búsqueda
y ciclo de vida determinista sin terminate().
"""

import os
import sys
import json
import re
import shutil
import fcntl
from typing import Dict, Any, List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QScrollArea, QFrame, QMessageBox,
    QPlainTextEdit, QGridLayout, QListWidget, QListWidgetItem,
    QSplitter, QTabWidget, QProgressBar, QLineEdit, QSizePolicy
)

def find_workspace_root() -> str:
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.exists(os.path.join(curr, "SCRIPTS", "mcp_profile_selector.py")):
            return curr
        curr = os.path.dirname(curr)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKSPACE_ROOT = os.environ.get("FLOYDIA_WORKSPACE", find_workspace_root())
SCRIPTS_DIR = os.path.join(WORKSPACE_ROOT, "SCRIPTS")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

class DefaultSkillsHelper:
    DEPRECATED_SERVERS = set()
    PROTECTED_USER_SKILLS = {
        "f-clientes", "f-descripcion", "f-handon-handoff", "f-harness-workflow",
        "f-mejora-prompt", "f-opti-floydia", "f-opti-notebooklm", "f-update-floydia"
    }
    SKILL_PRESETS = {
        "diario": {
            "name": "⚡ Diario Ultra-Ligero",
            "badge": "4 Skills",
            "description": "Continuidad, Arnés, Optimización y SRE Governor f-*.",
            "skills": ["f-handon-handoff", "f-mejora-prompt", "f-harness-workflow", "f-opti-floydia"]
        },
        "full": {
            "name": "🚀 Full Canónica v27",
            "badge": "8 Skills",
            "description": "Activa las 8 habilidades especializadas canónicas f-*.",
            "skills": [
                "f-clientes", "f-descripcion", "f-handon-handoff", "f-harness-workflow",
                "f-mejora-prompt", "f-opti-floydia", "f-opti-notebooklm", "f-update-floydia"
            ]
        }
    }
    
    @staticmethod
    def get_skills_catalog():
        catalog = []
        if os.path.exists(SKILLS_DIR):
            for item in os.listdir(SKILLS_DIR):
                if item.startswith("_") or item.startswith("."):
                    continue
                p = os.path.join(SKILLS_DIR, item)
                if os.path.isdir(p):
                    catalog.append({"name": item, "active": True, "desc": f"Skill: {item}"})
        if os.path.exists(SKILLS_ARCHIVE_DIR):
            for item in os.listdir(SKILLS_ARCHIVE_DIR):
                if item.startswith("_") or item.startswith("."):
                    continue
                p = os.path.join(SKILLS_ARCHIVE_DIR, item)
                if os.path.isdir(p):
                    catalog.append({"name": item, "active": False, "desc": f"Archived: {item}"})
        return sorted(catalog, key=lambda x: x["name"])

    @staticmethod
    def enable_skill(name: str):
        src = os.path.join(SKILLS_ARCHIVE_DIR, name)
        dst = os.path.join(SKILLS_DIR, name)
        if os.path.exists(src):
            shutil.move(src, dst)
            return True, "Skill activada"
        return False, "No encontrada"

    @staticmethod
    def disable_skill(name: str):
        src = os.path.join(SKILLS_DIR, name)
        dst = os.path.join(SKILLS_ARCHIVE_DIR, name)
        os.makedirs(SKILLS_ARCHIVE_DIR, exist_ok=True)
        if os.path.exists(src):
            shutil.move(src, dst)
            return True, "Skill archivada"
        return False, "No encontrada"

try:
    import mcp_profile_selector
except ImportError:
    mcp_profile_selector = DefaultSkillsHelper()

MCP_CONFIG_PATH = os.environ.get("MCP_CONFIG_PATH", os.path.expanduser("~/.gemini/config/mcp_config.json"))
MCP_BACKUP_PATH = os.path.expanduser("~/.gemini/config/mcp_config.json.bak")
OPENCODE_CONFIG = os.environ.get("OPENCODE_CONFIG_PATH", os.path.expanduser("~/.config/opencode/opencode.jsonc"))
ZED_CONFIG = os.environ.get("ZED_CONFIG_PATH", os.path.expanduser("~/.config/zed/settings.json"))
HERMES_CONFIG = os.environ.get("HERMES_CONFIG_PATH", os.path.expanduser("~/.hermes/config.yaml"))
QODER_CONFIG = os.environ.get("QODER_CONFIG_PATH", os.path.expanduser("~/.qoder/settings.json"))
DSH_CONFIG = os.path.expanduser("~/.dsh/profiles/web/cordis.patch.yml")
SKILLS_DIR = os.path.join(WORKSPACE_ROOT, ".agents", "skills")
SKILLS_ARCHIVE_DIR = os.path.join(SKILLS_DIR, "_archive")


def atomic_json_write(path: str, data: Any) -> None:
    """Escritura atómica — delega en el SSOT modules/state_store.atomic_write_json."""
    from modules.state_store import atomic_write_json as _ss_write
    _ss_write(path, data)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker, is_worker_running
)

# ── Ownership Registry & Fusión No Destructiva (FSU-008) ─────────────────────

_HERMES_MCP_TOP_RE = re.compile(r'(?m)^mcp_servers:\s*(#.*)?$')
_HERMES_ENTRY_RE = re.compile(r'^  ([A-Za-z0-9_\-.]+?):\s*(#.*)?$')
_HERMES_MARKER = "# ── Servidores MCP (Sincronizado por Floydia Suite) ──"


def _backup_config_file(path: str) -> None:
    """Backup rotativo simple (.bak) antes de una escritura con capacidad destructiva."""
    try:
        if os.path.exists(path):
            shutil.copy2(path, f"{path}.bak")
    except Exception:
        pass


def _parse_hermes_mcp_entries(block: str) -> List[Tuple[str, List[str]]]:
    """
    Parsea las entradas del bloque mcp_servers de config.yaml (claves a 2 espacios).
    Devuelve [(nombre, lineas_verbatim)] para preservar el formato original.
    """
    entries: List[Tuple[str, List[str]]] = []
    current: Optional[List[Any]] = None  # [nombre, lineas]
    for line in block.split("\n"):
        m = _HERMES_ENTRY_RE.match(line)
        if m:
            current = [m.group(1).strip(), [line]]
            entries.append((current[0], current[1]))
            continue
        if current is not None and (
            line.startswith("    ") or line.strip() == "" or line.strip().startswith("#")
        ):
            current[1].append(line)
        elif current is not None:
            current = None  # dedent inesperado: fin del bloque
    return entries


def _merge_hermes_mcp_content(
    content: str,
    generated_entries: Dict[str, List[str]],
    registry: Dict[str, Any],
) -> str:
    """
    Fusión no destructiva del bloque mcp_servers de ~/.hermes/config.yaml (FSU-008):
      - Entradas manuales del usuario (nunca gestionadas): preservadas verbatim.
      - Entradas gestionadas previamente: re-renderizadas, o eliminadas si la suite
        ya no las genera.
    Actualiza registry["resources"]["hermes"]["managed_names"] en memoria.
    """
    resources = registry.setdefault("resources", {})
    res_entry = resources.setdefault("hermes", {})
    prev_managed = set(res_entry.get("managed_names", []) or [])
    managed_now = set(generated_entries.keys())

    match = _HERMES_MCP_TOP_RE.search(content)
    if match:
        head = content[:match.start()]
        block = content[match.end():]
    else:
        head = content
        block = ""
    head = head.rstrip()
    # Evitar duplicar el marcador histórico de la suite en sincronizaciones sucesivas
    if head.endswith(_HERMES_MARKER):
        head = head[: -len(_HERMES_MARKER)].rstrip()

    preserved: List[List[str]] = []
    for name, entry_lines in _parse_hermes_mcp_entries(block):
        if name in managed_now or name in prev_managed:
            continue  # gestionadas por la suite: se re-renderizan o se eliminan
        preserved.append(entry_lines)  # entrada manual del usuario: intacta

    lines: List[str] = ["mcp_servers:"]
    for entry_lines in preserved:
        lines.extend(entry_lines)
    for name in generated_entries:
        lines.extend(generated_entries[name])

    res_entry["managed_names"] = sorted(managed_now)
    return (head + "\n" if head else "") + "\n".join(lines) + "\n"

CANONICAL_PROFILES = {
    "web-deploy": {
        "name": "🌐 Web Modo S & Deploy",
        "badge": "4 MCPs",
        "desc": "Modo S Estático (Vite/Firebase) & Novamira + Stitch UI + Obsidian Memory Bank + Playwright CT114.",
        "mcps": ["novamira-mcp", "stitch", "obsidian-mcp", "playwright-runner"]
    },
    "visual-design": {
        "name": "🎨 Diseño Visual & Retoque",
        "badge": "4 MCPs",
        "desc": "Google Colab GPU (BiRefNet/IC-Light) + Inkscape Vector + Stitch UI + Obsidian Memory Bank.",
        "mcps": ["colab", "inkscape_mcp", "stitch", "obsidian-mcp"]
    },
    "research": {
        "name": "🔬 AI Deep Research (MIT)",
        "badge": "2 MCPs",
        "desc": "NotebookLM Pipeline (50-200 fuentes) + Obsidian Memory Bank.",
        "mcps": ["notebooklm-mcp", "obsidian-mcp"]
    },
    "seo-audit": {
        "name": "📈 SEO & Growth Analytics",
        "badge": "3 MCPs",
        "desc": "Google Analytics 4 + Google Search Console + Playwright Runner.",
        "mcps": ["google-analytics", "google-search-console", "playwright-runner"]
    },
    "infra": {
        "name": "📡 Infraestructura & Proxmox",
        "badge": "2 MCPs",
        "desc": "Proxmox VE (CT114 consolidado) + Tuning del Sistema + Obsidian Memory Bank.",
        "mcps": ["proxmox-mcp", "obsidian-mcp"]
    },
    "default": {
        "name": "⚡ Diario Ultra-Ligero (SSOT)",
        "badge": "2 MCPs",
        "desc": "Perfil diario: Memory Bank (CT106) y validación Playwright (<1s carga).",
        "mcps": ["obsidian-mcp", "playwright-runner"]
    }
}


class SkillCardWidget(QFrame):
    toggled = pyqtSignal(str, bool)
    inspect_requested = pyqtSignal(str)

    def __init__(self, skill_data: dict, parent=None):
        super().__init__(parent)
        self.skill_data = skill_data
        self.skill_name = skill_data["name"]
        self.is_active = skill_data.get("active", True)
        self.setObjectName("SkillCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(68)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # Checkbox
        self.cb = QCheckBox()
        self.cb.setChecked(self.is_active)
        self.cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cb.stateChanged.connect(self._on_cb_changed)
        layout.addWidget(self.cb)

        # Info
        info_lay = QVBoxLayout()
        info_lay.setSpacing(2)

        h_row = QHBoxLayout()
        self.lbl_name = QLabel(self.skill_name)
        self.lbl_name.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        h_row.addWidget(self.lbl_name)

        if self.skill_name in getattr(mcp_profile_selector, "PROTECTED_USER_SKILLS", set()):
            badge_prot = QLabel("💎 CORE")
            badge_prot.setStyleSheet("background-color: #3B0764; color: #D8B4FE; font-size: 9px; font-weight: bold; border-radius: 3px; padding: 1px 5px;")
            h_row.addWidget(badge_prot)

        self.lbl_status = QLabel()
        self.update_status_label()
        h_row.addWidget(self.lbl_status)
        h_row.addStretch()
        info_lay.addLayout(h_row)

        desc = skill_data.get("desc", "") or "Habilidad especializada de automatización de agentes."
        self.lbl_desc = QLabel(desc)
        self.lbl_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
        self.lbl_desc.setWordWrap(True)
        info_lay.addWidget(self.lbl_desc)

        layout.addLayout(info_lay, stretch=1)

        # Botón Ver Markdown
        btn_view = QPushButton("👁️ Ver")
        btn_view.setObjectName("SecondaryBtn")
        btn_view.setFixedWidth(52)
        btn_view.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_view.clicked.connect(lambda: self.inspect_requested.emit(self.skill_name))
        layout.addWidget(btn_view)

        self.update_style()

    def _on_cb_changed(self, state):
        self.is_active = self.cb.isChecked()
        self.update_status_label()
        self.update_style()
        self.toggled.emit(self.skill_name, self.is_active)

    def update_status_label(self):
        if self.is_active:
            self.lbl_status.setText("🟢 ACTIVA")
            self.lbl_status.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 10px; font-weight: bold;")
        else:
            self.lbl_status.setText("📦 ARCHIVADA")
            self.lbl_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px; font-weight: bold;")

    def update_style(self):
        if self.is_active:
            self.setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_BORDER}; border-radius: 6px;")
        else:
            self.setStyleSheet("background-color: #080D14; border: 1px solid #14202E; border-radius: 6px;")


class SkillSyncWorker(CancellableThread):
    """Worker asíncrono para aplicar cambios de activación/archivo de skills sin bloquear la GUI."""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, int, int, str)

    def __init__(self, skills_list: List[dict], parent=None):
        super().__init__(parent)
        self.skills_list = [dict(s) for s in skills_list]

    def run(self):
        try:
            enabled_cnt = 0
            disabled_cnt = 0
            total = len(self.skills_list)
            if total == 0:
                self.finished_signal.emit(True, 0, 0, "No hay skills para sincronizar.")
                return

            for idx, s in enumerate(self.skills_list, start=1):
                if self.is_cancelled():
                    self.finished_signal.emit(False, enabled_cnt, disabled_cnt, "Sincronización cancelada.")
                    return

                name = s["name"]
                active = s["active"]
                if active:
                    ok, _ = mcp_profile_selector.enable_skill(name)
                    if ok:
                        enabled_cnt += 1
                else:
                    ok, _ = mcp_profile_selector.disable_skill(name)
                    if ok:
                        disabled_cnt += 1

                pct = int((idx / total) * 100)
                self.progress_signal.emit(pct, f"Sincronizando {name}...")

            self.finished_signal.emit(True, enabled_cnt, disabled_cnt, "Skills sincronizadas con éxito.")
        except Exception as exc:
            self.finished_signal.emit(False, 0, 0, f"Error en sincronización: {exc}")


class TabMcpSkills(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mcp_config_data: Dict[str, Any] = {}
        self.server_checkboxes: Dict[str, QCheckBox] = {}
        self.skills_list: List[Dict[str, Any]] = []
        self.skill_cards_map: Dict[str, SkillCardWidget] = {}
        self.sync_worker: Optional[SkillSyncWorker] = None

        self.init_ui()
        self.refresh_all()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # 1. Encabezado
        top_box = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("🎛️ MCP Cockpit & Skills Studio")
        title.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        
        subtitle = QLabel("Gestión unificada de servidores MCP (~/.gemini/config/mcp_config.json) y presupuesto de tokens de Skills")
        subtitle.setFont(QFont("Inter", 10))
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_box.addLayout(title_box)
        top_box.addStretch()

        btn_refresh = QPushButton("🔄 Recargar Todo")
        btn_refresh.setObjectName("SecondaryBtn")
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.clicked.connect(self.refresh_all)
        top_box.addWidget(btn_refresh)

        layout.addLayout(top_box)

        # 2. Tabs: Sub-pestaña MCP vs Sub-pestaña Skills
        self.tabs = QTabWidget()
        
        self.tab_mcp = QWidget()
        self.tab_skills = QWidget()

        self.tabs.addTab(self.tab_mcp, "🔌 Servidores MCP")
        self.tabs.addTab(self.tab_skills, "🧠 Skills de Agentes")

        self.init_mcp_subtab()
        self.init_skills_subtab()

        layout.addWidget(self.tabs)

    def init_mcp_subtab(self):
        lay = QVBoxLayout(self.tab_mcp)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Barra Superior de Presupuesto y Guardado
        top_card = QFrame()
        top_card.setProperty("class", "CardFrame")
        top_card_lay = QHBoxLayout(top_card)
        top_card_lay.setContentsMargins(12, 8, 12, 8)
        
        self.lbl_mcp_budget = QLabel("Presupuesto de MCPs: 0/5 (🟢 ÓPTIMO)")
        self.lbl_mcp_budget.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.lbl_mcp_budget.setStyleSheet(f"color: {COLOR_SUCCESS};")
        top_card_lay.addWidget(self.lbl_mcp_budget)

        self.bar_mcp_budget = QProgressBar()
        self.bar_mcp_budget.setRange(0, 5)
        self.bar_mcp_budget.setValue(0)
        self.bar_mcp_budget.setFixedWidth(140)
        top_card_lay.addWidget(self.bar_mcp_budget)
        top_card_lay.addStretch()

        self.btn_sync_opencode_mcp = QPushButton("⚡ Sync OpenCode")
        self.btn_sync_opencode_mcp.setObjectName("SecondaryBtn")
        self.btn_sync_opencode_mcp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sync_opencode_mcp.setToolTip("Propaga los servidores MCP activos hacia ~/.config/opencode/opencode.jsonc")
        self.btn_sync_opencode_mcp.clicked.connect(lambda: self.sync_mcps_to_opencode(silent=False))
        top_card_lay.addWidget(self.btn_sync_opencode_mcp)

        self.btn_sync_dsh_mcp = QPushButton("⚡ Sync DeepSeek (DSH)")
        self.btn_sync_dsh_mcp.setObjectName("SecondaryBtn")
        self.btn_sync_dsh_mcp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sync_dsh_mcp.setToolTip("Propaga los servidores MCP activos hacia ~/.dsh/profiles/web/cordis.patch.yml")
        self.btn_sync_dsh_mcp.clicked.connect(lambda: self.sync_mcps_to_dsh(silent=False))
        top_card_lay.addWidget(self.btn_sync_dsh_mcp)

        self.btn_propagate_all_mcps = QPushButton("🚀 Propagación Atómica 1-Clic")
        self.btn_propagate_all_mcps.setObjectName("SecondaryBtn")
        self.btn_propagate_all_mcps.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_propagate_all_mcps.setToolTip("Propaga los MCPs activos a todos los agentes: Antigravity, OpenCode, Zed, Hermes, Qoder y DSH")
        self.btn_propagate_all_mcps.clicked.connect(lambda: self.propagate_mcps_all_agents(silent=False))
        top_card_lay.addWidget(self.btn_propagate_all_mcps)

        self.btn_save_mcp = QPushButton("💾 Guardar y Aplicar")
        self.btn_save_mcp.setObjectName("PrimaryBtn")
        self.btn_save_mcp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_mcp.clicked.connect(self.save_mcp_config)
        top_card_lay.addWidget(self.btn_save_mcp)

        lay.addWidget(top_card)

        # Splitter: Perfiles Canónicos (Izquierda) / Servidores Individuales (Derecha)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Panel Izquierdo: Perfiles Canónicos
        left_box = QFrame()
        left_box.setProperty("class", "CardFrame")
        left_lay = QVBoxLayout(left_box)
        left_lay.setContentsMargins(10, 10, 10, 10)
        left_lay.setSpacing(8)

        lbl_prof_title = QLabel("🎯 Perfiles Canónicos de MCP")
        lbl_prof_title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        lbl_prof_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        left_lay.addWidget(lbl_prof_title)

        scroll_prof = QScrollArea()
        scroll_prof.setWidgetResizable(True)
        scroll_prof.setFrameShape(QFrame.Shape.NoFrame)
        prof_container = QWidget()
        prof_lay = QVBoxLayout(prof_container)
        prof_lay.setContentsMargins(0, 0, 0, 0)
        prof_lay.setSpacing(6)

        for p_key, p_info in CANONICAL_PROFILES.items():
            card = QFrame()
            card.setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 6px;")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(8, 6, 8, 6)
            c_lay.setSpacing(4)

            h_top = QHBoxLayout()
            lbl_n = QLabel(p_info["name"])
            lbl_n.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            badge = QLabel(p_info["badge"])
            badge.setStyleSheet(f"background-color: #1E3A5F; color: {COLOR_PRIMARY_CYAN}; font-size: 9px; font-weight: bold; border-radius: 3px; padding: 1px 4px;")
            h_top.addWidget(lbl_n)
            h_top.addStretch()
            h_top.addWidget(badge)
            c_lay.addLayout(h_top)

            lbl_d = QLabel(p_info["desc"])
            lbl_d.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
            lbl_d.setWordWrap(True)
            c_lay.addWidget(lbl_d)

            btn_apply = QPushButton("Activar Perfil")
            btn_apply.setObjectName("SecondaryBtn")
            btn_apply.setFixedHeight(24)
            btn_apply.setFont(QFont("Inter", 9, QFont.Weight.Bold))
            btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_apply.clicked.connect(lambda checked, k=p_key: self.apply_canonical_profile(k))
            c_lay.addWidget(btn_apply)

            prof_lay.addWidget(card)

        prof_lay.addStretch()
        scroll_prof.setWidget(prof_container)
        left_lay.addWidget(scroll_prof)

        # Panel Derecho: Switches de Servidores Individuales
        right_box = QFrame()
        right_box.setProperty("class", "CardFrame")
        right_lay = QVBoxLayout(right_box)
        right_lay.setContentsMargins(10, 10, 10, 10)
        right_lay.setSpacing(8)

        lbl_srv_title = QLabel("⚙️ Servidores MCP Instalados")
        lbl_srv_title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        lbl_srv_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        right_lay.addWidget(lbl_srv_title)

        srv_actions = QHBoxLayout()
        btn_sel_all = QPushButton("Activar Todos")
        btn_sel_all.setObjectName("SecondaryBtn")
        btn_sel_all.clicked.connect(lambda: self.set_all_mcps(True))
        btn_desel_all = QPushButton("Desactivar Todos")
        btn_desel_all.setObjectName("SecondaryBtn")
        btn_desel_all.clicked.connect(lambda: self.set_all_mcps(False))
        srv_actions.addWidget(btn_sel_all)
        srv_actions.addWidget(btn_desel_all)
        srv_actions.addStretch()
        right_lay.addLayout(srv_actions)

        srv_scroll = QScrollArea()
        srv_scroll.setWidgetResizable(True)
        srv_scroll.setFrameShape(QFrame.Shape.NoFrame)
        srv_container = QWidget()
        self.servers_vbox = QVBoxLayout(srv_container)
        self.servers_vbox.setContentsMargins(0, 0, 0, 0)
        self.servers_vbox.setSpacing(6)

        srv_scroll.setWidget(srv_container)
        right_lay.addWidget(srv_scroll)

        splitter.addWidget(left_box)
        splitter.addWidget(right_box)
        splitter.setSizes([340, 560])

        lay.addWidget(splitter, stretch=1)

    def init_skills_subtab(self):
        lay = QVBoxLayout(self.tab_skills)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # 1. Barra Superior de Presupuesto y Acciones de Guardado
        top_skills_card = QFrame()
        top_skills_card.setProperty("class", "CardFrame")
        top_card_lay = QHBoxLayout(top_skills_card)
        top_card_lay.setContentsMargins(12, 8, 12, 8)
        
        self.lbl_skills_budget = QLabel("Skills Activas: 0/10 (🟢 ÓPTIMO - <700 tokens)")
        self.lbl_skills_budget.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.lbl_skills_budget.setStyleSheet(f"color: {COLOR_SUCCESS};")
        top_card_lay.addWidget(self.lbl_skills_budget)
        top_card_lay.addStretch()

        self.btn_apply_skills = QPushButton("💾 APLICAR CAMBIOS DE SKILLS")
        self.btn_apply_skills.setObjectName("PrimaryBtn")
        self.btn_apply_skills.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply_skills.clicked.connect(self.apply_skills_changes)
        top_card_lay.addWidget(self.btn_apply_skills)

        lay.addWidget(top_skills_card)

        # 2. Splitter Principal: Presets Canónicos (Izquierda) / Skills & Visor (Derecha)
        splitter_main = QSplitter(Qt.Orientation.Horizontal)

        # Panel Izquierdo: Presets Canónicos de Skills
        left_presets_box = QFrame()
        left_presets_box.setProperty("class", "CardFrame")
        left_presets_lay = QVBoxLayout(left_presets_box)
        left_presets_lay.setContentsMargins(10, 10, 10, 10)
        left_presets_lay.setSpacing(8)

        lbl_pres_title = QLabel("🎯 Presets Canónicos de Skills")
        lbl_pres_title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        lbl_pres_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        left_presets_lay.addWidget(lbl_pres_title)

        scroll_presets = QScrollArea()
        scroll_presets.setWidgetResizable(True)
        scroll_presets.setFrameShape(QFrame.Shape.NoFrame)
        presets_container = QWidget()
        presets_lay = QVBoxLayout(presets_container)
        presets_lay.setContentsMargins(0, 0, 0, 0)
        presets_lay.setSpacing(6)

        for p_key, p_info in getattr(mcp_profile_selector, "SKILL_PRESETS", {}).items():
            card = QFrame()
            card.setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 6px;")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(8, 6, 8, 6)
            c_lay.setSpacing(4)

            h_top = QHBoxLayout()
            lbl_n = QLabel(p_info.get("name", p_key))
            lbl_n.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            badge = QLabel(p_info.get("badge", f"{len(p_info.get('skills', []))} Skills"))
            badge.setStyleSheet(f"background-color: #1E3A5F; color: {COLOR_PRIMARY_CYAN}; font-size: 9px; font-weight: bold; border-radius: 3px; padding: 1px 4px;")
            h_top.addWidget(lbl_n)
            h_top.addStretch()
            h_top.addWidget(badge)
            c_lay.addLayout(h_top)

            lbl_d = QLabel(p_info.get("description", ""))
            lbl_d.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
            lbl_d.setWordWrap(True)
            c_lay.addWidget(lbl_d)

            btn_apply = QPushButton("Activar Preset")
            btn_apply.setObjectName("SecondaryBtn")
            btn_apply.setFixedHeight(24)
            btn_apply.setFont(QFont("Inter", 9, QFont.Weight.Bold))
            btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_apply.clicked.connect(lambda checked, k=p_key: self.apply_skill_preset_ui(k))
            c_lay.addWidget(btn_apply)

            presets_lay.addWidget(card)

        presets_lay.addStretch()
        scroll_presets.setWidget(presets_container)
        left_presets_lay.addWidget(scroll_presets)
        splitter_main.addWidget(left_presets_box)

        # Panel Derecho: Filtros, Tarjetas Individuales y Visor
        right_content_box = QFrame()
        right_content_box.setProperty("class", "CardFrame")
        right_content_lay = QVBoxLayout(right_content_box)
        right_content_lay.setContentsMargins(10, 10, 10, 10)
        right_content_lay.setSpacing(8)

        # Barra de Filtros
        filter_row = QHBoxLayout()
        self.skill_search_input = QLineEdit()
        self.skill_search_input.setPlaceholderText("🔍 Buscar skill por nombre o descripción...")
        self.skill_search_input.setFixedWidth(240)
        
        self.skill_filter_timer = QTimer(self)
        self.skill_filter_timer.setSingleShot(True)
        self.skill_filter_timer.setInterval(150)
        self.skill_filter_timer.timeout.connect(self.render_skills_cards)
        self.skill_search_input.textChanged.connect(lambda _text: self.skill_filter_timer.start())
        filter_row.addWidget(self.skill_search_input)

        self.combo_skill_filter = QComboBox()
        self.combo_skill_filter.addItems(["Todas las Skills", "Solo Activas", "Solo Archivadas"])
        self.combo_skill_filter.currentIndexChanged.connect(self.render_skills_cards)
        filter_row.addWidget(self.combo_skill_filter)

        filter_row.addStretch()

        btn_all_s = QPushButton("☑️ Activar Todas")
        btn_all_s.setObjectName("SecondaryBtn")
        btn_all_s.clicked.connect(lambda: self.toggle_all_skills(True))
        filter_row.addWidget(btn_all_s)

        btn_none_s = QPushButton("⬜ Desactivar Todas")
        btn_none_s.setObjectName("SecondaryBtn")
        btn_none_s.clicked.connect(lambda: self.toggle_all_skills(False))
        filter_row.addWidget(btn_none_s)

        right_content_lay.addLayout(filter_row)

        # Sub-Splitter: Lista de Skills (Centro) / Visor Markdown (Derecha)
        sub_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Sub-Panel: Tarjetas de Skills con Checkbox
        skills_list_frame = QFrame()
        skills_list_lay = QVBoxLayout(skills_list_frame)
        skills_list_lay.setContentsMargins(0, 0, 0, 0)
        skills_list_lay.setSpacing(6)

        scroll_skills = QScrollArea()
        scroll_skills.setWidgetResizable(True)
        scroll_skills.setFrameShape(QFrame.Shape.NoFrame)
        scroll_container = QWidget()
        self.skills_vbox = QVBoxLayout(scroll_container)
        self.skills_vbox.setContentsMargins(0, 0, 0, 0)
        self.skills_vbox.setSpacing(6)

        scroll_skills.setWidget(scroll_container)
        skills_list_lay.addWidget(scroll_skills)
        sub_splitter.addWidget(skills_list_frame)

        # Sub-Panel: Visor de SKILL.md
        viewer_frame = QFrame()
        viewer_lay = QVBoxLayout(viewer_frame)
        viewer_lay.setContentsMargins(4, 0, 0, 0)
        viewer_lay.setSpacing(6)

        self.lbl_skill_view_title = QLabel("📄 Selecciona un Skill para inspeccionar su SKILL.md")
        self.lbl_skill_view_title.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.lbl_skill_view_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        viewer_lay.addWidget(self.lbl_skill_view_title)

        self.skill_content_viewer = QPlainTextEdit()
        self.skill_content_viewer.setReadOnly(True)
        self.skill_content_viewer.setStyleSheet(f"background-color: {COLOR_BG_DARK}; border: 1px solid {COLOR_BORDER}; font-family: monospace; font-size: 11px;")
        viewer_lay.addWidget(self.skill_content_viewer)

        sub_splitter.addWidget(viewer_frame)
        sub_splitter.setSizes([340, 360])

        right_content_lay.addWidget(sub_splitter, stretch=1)
        splitter_main.addWidget(right_content_box)
        splitter_main.setSizes([330, 670])

        lay.addWidget(splitter_main, stretch=1)

    def load_mcp_config(self):
        if not os.path.exists(MCP_CONFIG_PATH):
            return

        try:
            with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                self.mcp_config_data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo leer mcp_config.json: {e}")
            return

        mcp_servers = self.mcp_config_data.get("mcpServers", {})

        for i in reversed(range(self.servers_vbox.count())):
            w = self.servers_vbox.itemAt(i).widget()
            if w:
                w.setParent(None)

        self.server_checkboxes.clear()
        sorted_servers = sorted(mcp_servers.keys())

        for name in sorted_servers:
            if name in mcp_profile_selector.DEPRECATED_SERVERS or name.startswith("#"):
                continue
            server_info = mcp_servers[name]
            is_disabled = server_info.get("disabled", False)

            cb_frame = QFrame()
            cb_frame.setStyleSheet(f"background-color: #0E1A29; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 6px;")
            cb_lay = QHBoxLayout(cb_frame)
            cb_lay.setContentsMargins(8, 4, 8, 4)

            cb = QCheckBox(name)
            cb.setChecked(not is_disabled)
            cb.stateChanged.connect(self.update_mcp_budget_ui)
            cb.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            cb_lay.addWidget(cb)
            cb_lay.addStretch()

            cmd_preview = server_info.get("command", "")
            lbl_cmd = QLabel(os.path.basename(cmd_preview))
            lbl_cmd.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
            cb_lay.addWidget(lbl_cmd)

            self.server_checkboxes[name] = cb
            self.servers_vbox.addWidget(cb_frame)

        self.servers_vbox.addStretch()
        self.update_mcp_budget_ui()

    def update_mcp_budget_ui(self):
        active_count = sum(1 for cb in self.server_checkboxes.values() if cb.isChecked())
        self.bar_mcp_budget.setValue(min(5, active_count))

        if active_count <= 5:
            self.lbl_mcp_budget.setText(f"Presupuesto de MCPs: {active_count}/5 (🟢 ÓPTIMO)")
            self.lbl_mcp_budget.setStyleSheet(f"color: {COLOR_SUCCESS}; font-weight: 700;")
            self.bar_mcp_budget.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_SUCCESS}; }}")
        else:
            self.lbl_mcp_budget.setText(f"Presupuesto de MCPs: {active_count}/5 (⚠️ EXCESIVO)")
            self.lbl_mcp_budget.setStyleSheet(f"color: {COLOR_DANGER}; font-weight: 700;")
            self.bar_mcp_budget.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_DANGER}; }}")

    def set_all_mcps(self, checked: bool):
        for cb in self.server_checkboxes.values():
            cb.setChecked(checked)

    def apply_canonical_profile(self, profile_key: str):
        profile = CANONICAL_PROFILES.get(profile_key)
        if not profile:
            return

        target_mcps = set(profile["mcps"])
        for name, cb in self.server_checkboxes.items():
            cb.setChecked(name in target_mcps)

        QMessageBox.information(
            self,
            "Perfil Seleccionado",
            f"✅ Perfil '{profile['name']}' cargado en los switches.\nPresiona 'Guardar y Aplicar' para persistir en mcp_config.json."
        )

    def _get_active_mcp_specs(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Obtiene la lista de tuplas (nombre, spec) de los MCPs actualmente activos."""
        mcp_servers = self.mcp_config_data.get("mcpServers", {})
        active = []
        for name, srv in sorted(mcp_servers.items()):
            if name in getattr(mcp_profile_selector, "DEPRECATED_SERVERS", set()) or name.startswith("#"):
                continue
            cb = self.server_checkboxes.get(name)
            is_enabled = cb.isChecked() if cb is not None else not srv.get("disabled", False)
            if is_enabled:
                active.append((name, srv))
        return active

    def sync_mcps_to_opencode(self, silent: bool = False) -> bool:
        """Propaga los servidores MCP activos hacia ~/.config/opencode/opencode.jsonc."""
        try:
            active_servers = self._get_active_mcp_specs()
            opencode_mcp = {}

            for name, srv in active_servers:
                cmd = srv.get("command", "")
                args = srv.get("args", [])
                env = srv.get("env", {})

                if isinstance(cmd, list):
                    full_cmd = list(cmd) + list(args)
                else:
                    full_cmd = [cmd] + list(args) if cmd else []

                entry = {
                    "type": "local",
                    "command": full_cmd
                }
                if env:
                    entry["environment"] = env
                opencode_mcp[name] = entry

            opencode_cfg = {}
            if os.path.exists(OPENCODE_CONFIG):
                try:
                    from modules.state_store import load_jsonc
                    opencode_cfg = load_jsonc(OPENCODE_CONFIG)
                except Exception as parse_exc:
                    # Regla de seguridad: si la config existente no es parseable,
                    # NUNCA sobreescribir (se perderían MCPs/providers del usuario).
                    if not silent:
                        QMessageBox.warning(
                            self,
                            "OpenCode no sincronizado",
                            f"⚠️ No se pudo leer {OPENCODE_CONFIG} de forma segura "
                            f"({parse_exc}). Se omite la sincronización para no "
                            f"destruir la configuración existente."
                        )
                    return False

            if not opencode_cfg:
                opencode_cfg = {
                    "$schema": "https://opencode.ai/config.json",
                    "model": "deepseek/deepseek-chat",
                    "small_model": "mistral/ministral-8b-latest"
                }

            # Fusión no destructiva (FSU-008): preserva MCPs manuales del usuario.
            from modules.state_store import (
                load_managed_registry, merge_managed_section, save_managed_registry
            )
            registry = load_managed_registry()
            merged_mcp, _managed_now = merge_managed_section(
                opencode_cfg.get("mcp", {}), opencode_mcp, "opencode", registry
            )
            opencode_cfg["mcp"] = merged_mcp
            _backup_config_file(OPENCODE_CONFIG)
            os.makedirs(os.path.dirname(OPENCODE_CONFIG), exist_ok=True)
            atomic_json_write(OPENCODE_CONFIG, opencode_cfg)
            # Persistir el registro SOLO tras éxito de la escritura del target.
            save_managed_registry(registry)

            if not silent:
                QMessageBox.information(
                    self,
                    "OpenCode MCP Sincronizado",
                    f"✅ Sincronizados exitosamente {len(opencode_mcp)} servidores MCP en OpenCode:\n{OPENCODE_CONFIG}"
                )
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar MCPs con OpenCode: {e}")
            return False

    def sync_mcps_to_zed(self, silent: bool = False) -> bool:
        """Propaga los servidores MCP activos hacia ~/.config/zed/settings.json (context_servers)."""
        try:
            if not os.path.exists(ZED_CONFIG):
                return False

            with open(ZED_CONFIG, "r", encoding="utf-8") as f:
                zed_data = json.load(f)

            ctx_servers = zed_data.setdefault("context_servers", {})
            active_servers = self._get_active_mcp_specs()

            # Mapear nombres canónicos en Zed
            new_ctx = {}
            for name, srv in active_servers:
                key = "obsidian" if name in ("obsidian-mcp", "obsidian") else name
                if key == "novamira-mcp":
                    key = "novamira"
                entry = {
                    "command": srv.get("command", ""),
                    "args": srv.get("args", [])
                }
                if key == "stitch":
                    entry["source"] = "custom"
                new_ctx[key] = entry

            # Fusión no destructiva (FSU-008): preserva context_servers manuales.
            from modules.state_store import (
                load_managed_registry, merge_managed_section, save_managed_registry
            )
            registry = load_managed_registry()
            merged_ctx, _managed_now = merge_managed_section(
                zed_data.get("context_servers", {}) or {}, new_ctx, "zed", registry
            )
            zed_data["context_servers"] = merged_ctx
            _backup_config_file(ZED_CONFIG)
            atomic_json_write(ZED_CONFIG, zed_data)
            save_managed_registry(registry)

            if not silent:
                QMessageBox.information(
                    self,
                    "Zed MCP Sincronizado",
                    f"✅ Sincronizados exitosamente {len(new_ctx)} context_servers en Zed Editor:\n{ZED_CONFIG}"
                )
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar MCPs con Zed: {e}")
            return False

    def sync_mcps_to_hermes(self, silent: bool = False) -> bool:
        """Propaga los servidores MCP activos hacia ~/.hermes/config.yaml."""
        try:
            if not os.path.exists(HERMES_CONFIG):
                return False

            active_servers = self._get_active_mcp_specs()
            # Entradas generadas por la suite (una lista de líneas YAML por servidor)
            generated_entries: Dict[str, List[str]] = {}
            for name, srv in active_servers:
                key = name.replace("-mcp", "")
                cmd = srv.get("command", "")
                args = srv.get("args", [])
                entry_lines = [f"  {key}:", f"    command: {cmd}"]
                if args:
                    entry_lines.append("    args:")
                    for a in args:
                        entry_lines.append(f"      - {a}")
                generated_entries[key] = entry_lines

            with open(HERMES_CONFIG, "r", encoding="utf-8") as f:
                content = f.read()

            # Fusión no destructiva (FSU-008): preserva entradas manuales del usuario
            # dentro del bloque mcp_servers; solo elimina/actualiza las gestionadas.
            from modules.state_store import load_managed_registry, save_managed_registry, atomic_write_text
            registry = load_managed_registry()
            _backup_config_file(HERMES_CONFIG)
            new_content = _merge_hermes_mcp_content(content, generated_entries, registry)
            atomic_write_text(HERMES_CONFIG, new_content)
            save_managed_registry(registry)

            if not silent:
                QMessageBox.information(
                    self,
                    "Hermes MCP Sincronizado",
                    f"✅ Sincronizados exitosamente {len(active_servers)} servidores MCP en Hermes:\n{HERMES_CONFIG}"
                )
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar MCPs con Hermes: {e}")
            return False

    def sync_mcps_to_qoder(self, silent: bool = False) -> bool:
        """Propaga los servidores MCP activos hacia ~/.qoder/settings.json."""
        try:
            if not os.path.exists(QODER_CONFIG):
                return False

            with open(QODER_CONFIG, "r", encoding="utf-8") as f:
                qoder_data = json.load(f)

            active_servers = self._get_active_mcp_specs()
            new_servers = {}
            for name, srv in active_servers:
                entry = {"command": srv.get("command", "")}
                if srv.get("args"):
                    entry["args"] = srv.get("args")
                if srv.get("env"):
                    entry["env"] = srv.get("env")
                new_servers[name] = entry

            # Fusión no destructiva (FSU-008): preserva mcpServers manuales.
            from modules.state_store import (
                load_managed_registry, merge_managed_section, save_managed_registry
            )
            registry = load_managed_registry()
            merged_servers, _managed_now = merge_managed_section(
                qoder_data.get("mcpServers", {}) or {}, new_servers, "qoder", registry
            )
            qoder_data["mcpServers"] = merged_servers
            _backup_config_file(QODER_CONFIG)
            atomic_json_write(QODER_CONFIG, qoder_data)
            save_managed_registry(registry)

            if not silent:
                QMessageBox.information(
                    self,
                    "Qoder MCP Sincronizado",
                    f"✅ Sincronizados exitosamente {len(new_servers)} servidores MCP en Qoder:\n{QODER_CONFIG}"
                )
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar MCPs con Qoder: {e}")
            return False

    def sync_mcps_to_dsh(self, silent: bool = False) -> bool:
        """Propaga los servidores MCP activos hacia ~/.dsh/profiles/web/cordis.patch.yml para DeepSeek Harness."""
        try:
            dsh_patch_path = os.path.expanduser("~/.dsh/profiles/web/cordis.patch.yml")
            if not os.path.exists(os.path.dirname(dsh_patch_path)):
                return False

            active_servers = self._get_active_mcp_specs()
            ide_internal_mcps = {"notebooks", "visualization", "data-agent-kit"}
            yaml_unsafe = {'@', '#', '!', '&', '*', '{', '}', '[', ']', '|', '>', ',', '?', ':', '-', ' '}

            def yaml_val(v: str) -> str:
                if not v:
                    return '""'
                if any(c in v for c in yaml_unsafe) or v.startswith(('%', '`')):
                    return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
                return v

            active_entries = []
            for name, srv in active_servers:
                if name in ide_internal_mcps:
                    continue
                cmd = srv.get("command", "")
                args = srv.get("args", [])
                env = srv.get("env", {})

                lines = [
                    f"    - id: mcp-{name}",
                    f"      name: '@deepseek-ai/dsh-mcp-client'",
                    f"      config:",
                    f"        transport: stdio",
                    f"        serverName: {name}",
                    f"        command: {yaml_val(cmd)}",
                ]
                if args:
                    lines.append("        args:")
                    for arg in args:
                        lines.append(f"          - {yaml_val(arg)}")
                else:
                    lines.append("        args: []")

                lines.append(f"        cwd: {WORKSPACE_ROOT}")
                if env:
                    lines.append("        env:")
                    for k, v in env.items():
                        lines.append(f"          {k}: {yaml_val(v)}")
                lines.append("        failOnStartupError: false")
                active_entries.append("\n".join(lines))

            header = f"# cordis.patch.yml — Sincronizado automáticamente por FloydIA Suite\n"
            parts = [header]
            if active_entries:
                parts.append("- insert:\n" + "\n\n".join(active_entries) + "\n")
            else:
                parts.append("# Sin MCPs activos\n")

            parts.append("""- id: llm-deepseek
  disabled: true

- id: sandbox-policy
  config:
    mode: danger-full-access
    workspaceRoot: """ + WORKSPACE_ROOT + """

- id: approval
  config:
    policy: never
""")
            content = "\n".join(parts)
            with open(dsh_patch_path, "w", encoding="utf-8") as f:
                f.write(content)

            if not silent:
                QMessageBox.information(
                    self,
                    "DSH MCP Sincronizado",
                    f"✅ Sincronizados exitosamente {len(active_entries)} servidores MCP en DeepSeek Harness:\n{dsh_patch_path}"
                )
            return True
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"No se pudo sincronizar MCPs con DSH: {e}")
            return False

    def propagate_mcps_all_agents(self, silent: bool = False) -> Dict[str, bool]:
        """Propaga atómicamente la configuración activa a todos los agentes soportados."""
        results = {}
        # 1. Antigravity IDE
        if os.path.exists(MCP_CONFIG_PATH):
            mcp_servers = self.mcp_config_data.get("mcpServers", {})
            for name, cb in self.server_checkboxes.items():
                if name in mcp_servers:
                    mcp_servers[name]["disabled"] = not cb.isChecked()
            atomic_json_write(MCP_CONFIG_PATH, self.mcp_config_data)
            results["Antigravity IDE"] = True
        else:
            results["Antigravity IDE"] = False

        # 2. Clientes locales
        results["OpenCode"] = self.sync_mcps_to_opencode(silent=True)
        results["Zed Editor"] = self.sync_mcps_to_zed(silent=True)
        results["Hermes"] = self.sync_mcps_to_hermes(silent=True)
        results["Qoder"] = self.sync_mcps_to_qoder(silent=True)
        results["DeepSeek Harness"] = self.sync_mcps_to_dsh(silent=True)

        if not silent:
            active_cnt = sum(1 for cb in self.server_checkboxes.values() if cb.isChecked())
            status_lines = []
            for agent, ok in results.items():
                icon = "✅" if ok else "⚠️"
                status_lines.append(f"  {icon} {agent}")
            QMessageBox.information(
                self,
                "Propagación Atómica 1-Clic",
                f"🚀 Propagación de {active_cnt} servidores MCP activos completada:\n\n" + "\n".join(status_lines)
            )
        return results

    def save_mcp_config(self):
        if not os.path.exists(MCP_CONFIG_PATH):
            return

        try:
            shutil.copy2(MCP_CONFIG_PATH, MCP_BACKUP_PATH)

            mcp_servers = self.mcp_config_data.get("mcpServers", {})
            for name, cb in self.server_checkboxes.items():
                if name in mcp_servers:
                    mcp_servers[name]["disabled"] = not cb.isChecked()

            atomic_json_write(MCP_CONFIG_PATH, self.mcp_config_data)

            # Propagación atómica 1-clic a todos los agentes
            self.propagate_mcps_all_agents(silent=True)

            active_cnt = sum(1 for cb in self.server_checkboxes.values() if cb.isChecked())
            QMessageBox.information(
                self,
                "Configuración Guardada y Propagada",
                f"✅ mcp_config.json actualizado exitosamente.\n\n"
                f"• MCPs Activos: {active_cnt}\n"
                f"• Sincronizado con: Antigravity, OpenCode, Zed, Hermes, Qoder y DSH\n"
                f"• Backup generado: {MCP_BACKUP_PATH}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error al Guardar", f"❌ Error guardando configuración: {e}")

    # ── GESTIÓN DE SKILLS ───────────────────────────────────────────────────
    def load_skills_catalog(self):
        try:
            self.skills_list = mcp_profile_selector.get_skills_catalog()
        except Exception:
            self.skills_list = []
        self.render_skills_cards()

    def render_skills_cards(self):
        while self.skills_vbox.count():
            item = self.skills_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                self.skills_vbox.removeItem(item)

        self.skill_cards_map.clear()
        active_count = 0
        q = self.skill_search_input.text().lower().strip()
        filter_mode = self.combo_skill_filter.currentIndex()

        for s in self.skills_list:
            if s["active"]:
                active_count += 1

            if filter_mode == 1 and not s["active"]:
                continue
            if filter_mode == 2 and s["active"]:
                continue

            if q and (q not in s["name"].lower() and q not in s.get("desc", "").lower()):
                continue

            card = SkillCardWidget(s)
            card.toggled.connect(self.on_skill_toggled)
            card.inspect_requested.connect(self.inspect_skill)
            self.skill_cards_map[s["name"]] = card
            self.skills_vbox.addWidget(card)

        self.skills_vbox.addStretch()

        if active_count <= 10:
            self.lbl_skills_budget.setText(f"Skills Activas: {active_count}/10 (🟢 ÓPTIMO - <700 tokens)")
            self.lbl_skills_budget.setStyleSheet(f"color: {COLOR_SUCCESS};")
        else:
            self.lbl_skills_budget.setText(f"Skills Activas: {active_count}/10 (⚠️ SOBRECARGA DE TOKENS)")
            self.lbl_skills_budget.setStyleSheet(f"color: {COLOR_DANGER};")

    def on_skill_toggled(self, skill_name: str, active: bool):
        for s in self.skills_list:
            if s["name"] == skill_name:
                s["active"] = active
                break

        active_count = sum(1 for s in self.skills_list if s["active"])
        if active_count <= 10:
            self.lbl_skills_budget.setText(f"Skills Activas: {active_count}/10 (🟢 ÓPTIMO - <700 tokens)")
            self.lbl_skills_budget.setStyleSheet(f"color: {COLOR_SUCCESS};")
        else:
            self.lbl_skills_budget.setText(f"Skills Activas: {active_count}/10 (⚠️ SOBRECARGA DE TOKENS)")
            self.lbl_skills_budget.setStyleSheet(f"color: {COLOR_DANGER};")

    def toggle_all_skills(self, checked: bool):
        for s in self.skills_list:
            s["active"] = checked
        self.render_skills_cards()

    def apply_skill_preset_ui(self, preset_key: str):
        preset = mcp_profile_selector.SKILL_PRESETS.get(preset_key)
        if not preset:
            return
        target_skills = set(preset["skills"])
        for s in self.skills_list:
            s["active"] = (s["name"] in target_skills)
        self.render_skills_cards()
        QMessageBox.information(
            self,
            "Preset Seleccionado",
            f"✅ Preset '{preset.get('name', preset_key)}' cargado ({len(target_skills)} skills marcadas).\n"
            f"Presiona 'APLICAR CAMBIOS DE SKILLS' para persistir en disco."
        )

    def apply_skills_changes(self):
        if is_worker_running(self.sync_worker):
            return

        self.btn_apply_skills.setEnabled(False)
        self.btn_apply_skills.setText("⏳ APLICANDO CAMBIOS...")

        self.sync_worker = SkillSyncWorker(self.skills_list)
        self.sync_worker.finished_signal.connect(self._on_skills_sync_finished)
        self.sync_worker.finished.connect(self._on_sync_worker_finished)
        self.sync_worker.start()

    def _on_sync_worker_finished(self):
        if self.sync_worker:
            self.sync_worker.deleteLater()
            self.sync_worker = None

    def _on_skills_sync_finished(self, success: bool, enabled_cnt: int, disabled_cnt: int, msg: str):
        self.btn_apply_skills.setEnabled(True)
        self.btn_apply_skills.setText("💾 APLICAR CAMBIOS DE SKILLS")
        self.load_skills_catalog()

        if success:
            QMessageBox.information(
                self,
                "Skills Sincronizadas",
                f"✅ Cambios aplicados con éxito en segundo plano:\n\n"
                f"• {enabled_cnt} Skills Activas en .agents/skills/\n"
                f"• {disabled_cnt} Skills Archivadas en .agents/skills/_archive/\n"
                f"• Presupuesto de contexto optimizado."
            )
        else:
            QMessageBox.critical(self, "Error al Aplicar Skills", f"❌ {msg}")

    def inspect_skill(self, skill_name: str):
        skill_item = next((s for s in self.skills_list if s["name"] == skill_name), None)
        if not skill_item:
            return

        self.lbl_skill_view_title.setText(f"📄 {skill_name} ({'Activa' if skill_item['active'] else 'Archivada'})")
        path = skill_item["path"]
        md_file = os.path.join(path, "SKILL.md") if os.path.isdir(path) else path

        if os.path.exists(md_file):
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()
                self.skill_content_viewer.setPlainText(content)
            except Exception as e:
                self.skill_content_viewer.setPlainText(f"Error al leer SKILL.md: {e}")
        else:
            self.skill_content_viewer.setPlainText("No se encontró el archivo SKILL.md.")

    def refresh_all(self):
        self.load_mcp_config()
        self.load_skills_catalog()

    def cleanup(self):
        """Hook de shutdown determinista."""
        if self.sync_worker is not None:
            stop_worker(self.sync_worker, timeout_ms=1500)
            self.sync_worker = None
