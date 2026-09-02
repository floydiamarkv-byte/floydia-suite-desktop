#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  ⚡ FLOYDIA SUITE 2.0 — Centro Unificado de Comando, SRE y Telemetría IA         ║
║  Ecosistema FloydIA: HP15 (Arch SSOT) ↔ Proxmox CT114 / CT106 ↔ MikroTik         ║
║  Diseño: PyQt6 Modern Dashboard (FLOYDIA V6 Brand System)                        ║
║  Arquitectura: Lazy Loading de Pestañas & Persistencia Transaccional             ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import logging
import argparse

logger = logging.getLogger("floydia_suite")

# Asegurar que el directorio de la suite esté en el path
SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from PyQt6.QtCore import Qt, QSize, QPoint, QRect, QByteArray
from PyQt6.QtGui import QIcon, QFont, QPixmap, QCloseEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QStatusBar,
    QSizePolicy
)

from theme import (
    FLOYDIA_SUITE_QSS, ICON_APP, SIDEBAR_LOGO, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_BG_DARK, COLOR_BORDER, COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED
)
from modules.state_store import atomic_read_json, atomic_write_json, utc_now_iso
from modules.tab_reboot import TabReboot
from modules.tab_optimizer import TabOptimizer
from modules.tab_mcp_skills import TabMcpSkills
from modules.tab_radar import TabRadar
from modules.tab_api_manager import TabApiManager
from modules.tab_diagnostics import TabDiagnostics
from modules.tab_cleaner import TabCleaner

SESSION_STATE_FILE = os.path.join(SUITE_DIR, "cache", "session_state.json")

TAB_MODULE_KEYS = [
    "tab_reboot",
    "tab_optimizer",
    "tab_cleaner",
    "tab_mcp_skills",
    "tab_radar",
    "tab_api_manager",
    "tab_diagnostics"
]


class FloydIASuiteApp(QMainWindow):
    def __init__(self, initial_tab: int = 0):
        super().__init__()
        self.setWindowTitle("FloydIA Suite 2.0 — Centro Unificado de Comando y SRE")
        self.resize(1180, 800)
        self.setMinimumSize(1000, 660)
        
        if ICON_APP and os.path.exists(ICON_APP):
            self.setWindowIcon(QIcon(ICON_APP))

        self.nav_buttons = []
        self.tab_instances = [None] * len(TAB_MODULE_KEYS)
        self.tab_factories = [
            lambda: TabReboot(),
            lambda: TabOptimizer(),
            lambda: TabCleaner(),
            lambda: TabMcpSkills(),
            lambda: TabRadar(),
            lambda: TabApiManager(),
            lambda: TabDiagnostics()
        ]
        self.init_ui(initial_tab)
        self.restore_session_state(initial_tab)

    def init_ui(self, initial_tab: int):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 1. SIDEBAR DE NAVEGACIÓN ──────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar_lay = QVBoxLayout(sidebar)
        sidebar_lay.setContentsMargins(14, 16, 14, 16)
        sidebar_lay.setSpacing(8)

        # Brand / Logo Header
        brand_container = QFrame()
        brand_container.setStyleSheet("background: transparent; border: none;")
        brand_lay = QVBoxLayout(brand_container)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(6)

        logo_loaded = False
        if SIDEBAR_LOGO and os.path.exists(SIDEBAR_LOGO):
            try:
                pix = QPixmap(SIDEBAR_LOGO)
                if not pix.isNull():
                    lbl_logo_img = QLabel()
                    scaled_pix = pix.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pix.width() > 210:
                        scaled_pix = pix.scaledToWidth(200, Qt.TransformationMode.SmoothTransformation)
                    lbl_logo_img.setPixmap(scaled_pix)
                    lbl_logo_img.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    brand_lay.addWidget(lbl_logo_img)
                    logo_loaded = True
            except Exception:
                logo_loaded = False

        if not logo_loaded:
            lbl_brand_name = QLabel("FLOYDIA SUITE")
            lbl_brand_name.setFont(QFont("Inter", 14, QFont.Weight.Bold))
            lbl_brand_name.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN}; letter-spacing: 1px;")
            brand_lay.addWidget(lbl_brand_name)

        lbl_brand_sub = QLabel("SRE & AI COMMAND HUB 2.0")
        lbl_brand_sub.setFont(QFont("Inter", 8, QFont.Weight.DemiBold))
        lbl_brand_sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; letter-spacing: 0.5px;")
        brand_lay.addWidget(lbl_brand_sub)
        sidebar_lay.addWidget(brand_container)

        # Separador Neón
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; margin: 8px 0px;")
        sidebar_lay.addWidget(sep)

        # Botones de Navegación
        nav_items = [
            ("🔄", "Reboot Hub", "Control de Infraestructura"),
            ("⚡", "SRE Optimizer", "Optimización & RAM"),
            ("🧹", "SRE Cleaner", "BleachBit & Multi-Perfil"),
            ("🧩", "MCP & Skills", "Studio de Habilidades"),
            ("🛰️", "AI Radar", "Observatorio de Modelos"),
            ("🔑", "API Manager", "Gestión de Endpoints"),
            ("📡", "SRE Diag", "Diagnóstico de Red")
        ]

        for i, (icon, title, desc) in enumerate(nav_items):
            btn = QPushButton()
            btn.setObjectName(f"NavBtn_{i}")
            btn.setCheckable(False)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setFixedHeight(54)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

            btn_lay = QHBoxLayout(btn)
            btn_lay.setContentsMargins(12, 6, 12, 6)
            btn_lay.setSpacing(10)

            lbl_icon = QLabel(icon)
            lbl_icon.setFont(QFont("Inter", 16))
            lbl_icon.setStyleSheet("background: transparent; border: none;")
            btn_lay.addWidget(lbl_icon)

            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            lbl_title = QLabel(title)
            lbl_title.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            lbl_title.setStyleSheet("background: transparent; border: none;")

            lbl_desc = QLabel(desc)
            lbl_desc.setFont(QFont("Inter", 7))
            lbl_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent; border: none;")

            text_box.addWidget(lbl_title)
            text_box.addWidget(lbl_desc)
            btn_lay.addLayout(text_box)
            btn_lay.addStretch()

            btn.clicked.connect(lambda checked, idx=i: self.switch_tab(idx))
            self.nav_buttons.append(btn)
            sidebar_lay.addWidget(btn)

        sidebar_lay.addStretch()

        # Footer Sidebar con Status Rápido
        footer_frame = QFrame()
        footer_frame.setStyleSheet(f"background-color: {COLOR_BG_DARK}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 6px;")
        footer_lay = QVBoxLayout(footer_frame)
        footer_lay.setContentsMargins(8, 6, 8, 6)
        footer_lay.setSpacing(4)

        lbl_env = QLabel("🟢 HP15 Arch SSOT (Host)")
        lbl_env.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        lbl_env.setStyleSheet("color: #10B981; background: transparent; border: none;")
        footer_lay.addWidget(lbl_env)

        lbl_sync = QLabel("CT106 Obsidian ↔ CT114 Hybrid")
        lbl_sync.setFont(QFont("Inter", 7))
        lbl_sync.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent; border: none;")
        footer_lay.addWidget(lbl_sync)

        sidebar_lay.addWidget(footer_frame)
        main_layout.addWidget(sidebar)

        # ── 2. ÁREA DE CONTENIDO PRINCIPAL ────────────────────────────────────
        content_container = QWidget()
        content_lay = QVBoxLayout(content_container)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(0)

        # Top Bar Contextual
        header_frame = QFrame()
        header_frame.setObjectName("HeaderFrame")
        header_frame.setStyleSheet(f"background-color: {COLOR_BG_DARK}; border-bottom: 1px solid {COLOR_BORDER};")
        header_lay = QHBoxLayout(header_frame)
        header_lay.setContentsMargins(20, 12, 20, 12)

        self.lbl_current_title = QLabel("Dashboard")
        self.lbl_current_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        self.lbl_current_title.setStyleSheet(f"color: {COLOR_TEXT_MAIN};")
        header_lay.addWidget(self.lbl_current_title)
        header_lay.addStretch()

        # Botón Acción Rápida Global
        btn_fast_clean = QPushButton("⚡ Limpieza SRE Rápida")
        btn_fast_clean.setObjectName("BtnFastClean")
        btn_fast_clean.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        btn_fast_clean.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_fast_clean.clicked.connect(self.quick_clean_action)
        header_lay.addWidget(btn_fast_clean)

        content_lay.addWidget(header_frame)

        # Stack de Pestañas (Contenedores para Lazy Loading)
        self.stack = QStackedWidget()
        for i in range(len(TAB_MODULE_KEYS)):
            container = QWidget()
            c_lay = QVBoxLayout(container)
            c_lay.setContentsMargins(0, 0, 0, 0)
            self.stack.addWidget(container)

        content_lay.addWidget(self.stack)
        main_layout.addWidget(content_container)

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("background-color: #070D14; color: #94A3B8; border-top: 1px solid #1E3A5F; padding: 4px;")
        self.status_bar.showMessage("🟢 FloydIA Suite 2.0 activa. Persistencia atómica de sesión habilitada.")
        self.setStatusBar(self.status_bar)

        # Activar pestaña inicial bajo demanda
        self.switch_tab(initial_tab)

    def switch_tab(self, index: int):
        if not (0 <= index < len(TAB_MODULE_KEYS)):
            return

        # ⚡ Lazy Loading: Instanciar la pestaña únicamente en su primer acceso
        if self.tab_instances[index] is None:
            try:
                tab_widget = self.tab_factories[index]()
                self.tab_instances[index] = tab_widget
                container = self.stack.widget(index)
                container.layout().addWidget(tab_widget)
            except Exception as exc:
                self.status_bar.showMessage(f"❌ Error cargando pestaña {index}: {exc}", 5000)
                return

        self.stack.setCurrentIndex(index)
        titles = [
            "🔄 Control de Infraestructura & Reboot Hub",
            "⚡ Optimizador SRE & Liberación de Memoria",
            "🧹 SRE BleachBit Cleaner — Limpieza Segura Multi-Perfil",
            "🧩 Gestor de MCPs & Skills Studio",
            "🛰️ AI Radar & Observatorio de Modelos",
            "🔑 Gestor de APIs, Endpoints & Propagación",
            "📡 Diagnóstico de Red & SRE Logs"
        ]
        if index < len(titles):
            self.lbl_current_title.setText(titles[index])

        for i, btn in enumerate(self.nav_buttons):
            if i == index:
                btn.setProperty("active", "true")
            else:
                btn.setProperty("active", "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def quick_clean_action(self):
        self.switch_tab(1)
        opt_tab = self.tab_instances[1]
        if opt_tab and hasattr(opt_tab, "run_all_optimizations"):
            opt_tab.run_all_optimizations()

    def _collect_window_geometry(self) -> dict:
        geo: dict = {}
        if self.isMaximized():
            geo["maximized"] = True
            r = self.normalGeometry()
        else:
            geo["maximized"] = False
            r = self.geometry()
        geo.update({
            "x": r.x(), "y": r.y(),
            "width": r.width(), "height": r.height(),
        })
        try:
            geo["geometry_b64"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        except Exception:
            geo["geometry_b64"] = ""
        return geo

    def _restore_geometry_from_coords(self, win: dict) -> None:
        """Fallback: restaura por coordenadas solo si caen dentro de una pantalla conectada."""
        try:
            x, y = int(win["x"]), int(win["y"])
            w, h = int(win["width"]), int(win["height"])
        except (KeyError, TypeError, ValueError):
            return
        if QGuiApplication.screenAt(QPoint(x, y)) is None:
            return
        if w < 400 or h < 300:
            return
        self.setGeometry(QRect(x, y, w, h))

    def restore_session_state(self, fallback_tab: int = 0) -> None:
        """
        Restaura geometría de ventana, pestaña activa y estado de módulos.
        Tolerante a fallos: cualquier inconsistencia degrada a valores por defecto.
        """
        state = atomic_read_json(SESSION_STATE_FILE)
        if not state:
            return

        # 1. Geometría de ventana
        win = state.get("window", {})
        geom_b64 = win.get("geometry_b64")
        restored_geom = False
        if geom_b64:
            try:
                raw_bytes = QByteArray.fromBase64(geom_b64.encode("ascii"))
                restored_geom = self.restoreGeometry(raw_bytes)
            except Exception:
                restored_geom = False

        if not restored_geom:
            self._restore_geometry_from_coords(win)

        if win.get("maximized"):
            self.setWindowState(Qt.WindowState.WindowMaximized)

        # 2. Pestaña activa (si el usuario no pasó un flag explícito por CLI)
        if fallback_tab == 0 and "active_tab" in state:
            try:
                target_tab = int(state.get("active_tab", 0))
                if 0 <= target_tab < len(TAB_MODULE_KEYS):
                    self.switch_tab(target_tab)
            except Exception:
                pass

        # 3. Restaurar módulos instanciados
        modules = state.get("modules", {})
        for idx, key in enumerate(TAB_MODULE_KEYS):
            mod_data = modules.get(key)
            if mod_data and self.tab_instances[idx] is not None:
                tab_obj = self.tab_instances[idx]
                restore_hook = getattr(tab_obj, "restore_state", None)
                if callable(restore_hook):
                    try:
                        restore_hook(mod_data)
                    except Exception as exc:
                        logger.warning("Error restaurando estado en %s: %s", key, exc)

    def _collect_session_state(self) -> dict:
        """Recopila el estado completo de la UI y de las pestañas instanciadas."""
        current_idx = self.stack.currentIndex() if hasattr(self, "stack") else 0
        state = {
            "version": 1,
            "saved_at": utc_now_iso(),
            "window": self._collect_window_geometry(),
            "active_tab": current_idx,
            "modules": {}
        }
        for idx, key in enumerate(TAB_MODULE_KEYS):
            tab_obj = self.tab_instances[idx]
            if tab_obj is not None:
                save_hook = getattr(tab_obj, "save_state", None)
                if callable(save_hook):
                    try:
                        state["modules"][key] = save_hook()
                    except Exception as exc:
                        logger.warning("Error en save_state de %s: %s", key, exc)
        return state

    def closeEvent(self, event: QCloseEvent):
        """
        Apagado ordenado y determinista en 3 fases:
          FASE 1: Detener timers y workers de las pestañas.
          FASE 2: Recopilar estado de sesión de UI y módulos.
          FASE 3: Persistencia atómica de session_state.json.
        """
        if hasattr(self, "status_bar") and self.status_bar:
            self.status_bar.showMessage("🛑 Guardando estado y cerrando sesión limpia...")

        # FASE 1: Detener workers asíncronos
        for tab in self.tab_instances:
            if tab is not None:
                hook = getattr(tab, "shutdown", None) or getattr(tab, "cleanup", None)
                if callable(hook):
                    try:
                        hook()
                    except Exception as exc:
                        logger.warning("Error en shutdown de %s: %s", type(tab).__name__, exc)

        # FASE 2 & 3: Recopilar y guardar estado de sesión atómicamente
        try:
            session_state = self._collect_session_state()
            atomic_write_json(SESSION_STATE_FILE, session_state)
            logger.info("Estado de sesión guardado atómicamente en %s", SESSION_STATE_FILE)
        except Exception as exc:
            logger.exception("Error guardando session_state.json (no bloquea el cierre): %s", exc)

        event.accept()


def main():
    import signal
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="FloydIA Suite 2.0 — Centro Unificado de Comando")
    parser.add_argument("--tab", type=str, default="0", help="Pestaña inicial (reboot, optimizer, cleaner, mcp, radar, apis, diag)")
    args = parser.parse_args()

    tab_map = {
        "0": 0, "reboot": 0,
        "1": 1, "optimizer": 1, "opti": 1,
        "2": 2, "cleaner": 2, "bleachbit": 2, "clean": 2,
        "3": 3, "mcp": 3, "skills": 3,
        "4": 4, "radar": 4, "ai": 4,
        "5": 5, "apis": 5, "api": 5, "keys": 5,
        "6": 6, "diag": 6, "network": 6
    }
    init_tab = tab_map.get(args.tab.lower(), 0)

    app = QApplication(sys.argv)
    app.setStyleSheet(FLOYDIA_SUITE_QSS)
    
    window = FloydIASuiteApp(initial_tab=init_tab)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
