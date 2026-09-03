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
from typing import Optional

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

# Lazy Loading REAL (FSU-016): los módulos de pestañas solo se importan en su primer
# acceso. El cold start ya no paga el import de las pestañas pesadas (radar, cleaner).
TAB_SPECS = [
    ("modules.tab_reboot", "TabReboot"),
    ("modules.tab_optimizer", "TabOptimizer"),
    ("modules.tab_cleaner", "TabCleaner"),
    ("modules.tab_mcp_skills", "TabMcpSkills"),
    ("modules.tab_radar", "TabRadar"),
    ("modules.tab_api_manager", "TabApiManager"),
    ("modules.tab_diagnostics", "TabDiagnostics"),
]

TAB_MODULE_KEYS = [
    "tab_reboot",
    "tab_optimizer",
    "tab_cleaner",
    "tab_mcp_skills",
    "tab_radar",
    "tab_api_manager",
    "tab_diagnostics"
]


def _load_tab_class(index: int):
    """Import diferido de la clase de una pestaña (lazy import real)."""
    import importlib
    module_name, class_name = TAB_SPECS[index]
    module = importlib.import_module(module_name)
    return getattr(module, class_name)

SESSION_STATE_FILE = os.path.join(SUITE_DIR, "cache", "session_state.json")


class FloydIASuiteApp(QMainWindow):
    def __init__(self, initial_tab: Optional[int] = None):
        super().__init__()
        self.setWindowTitle("FloydIA Suite 2.0 — Centro Unificado de Comando y SRE")
        self.resize(1180, 800)
        self.setMinimumSize(1000, 660)
        
        if ICON_APP and os.path.exists(ICON_APP):
            self.setWindowIcon(QIcon(ICON_APP))

        self.nav_buttons = []
        self.tab_instances = [None] * len(TAB_MODULE_KEYS)
        self.tab_factories = [
            (lambda i=i: _load_tab_class(i)) for i in range(len(TAB_SPECS))
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
        self.switch_tab(initial_tab if initial_tab is not None else 0)

    def switch_tab(self, index: int):
        if not (0 <= index < len(TAB_MODULE_KEYS)):
            return

        # ⚡ Lazy Loading: Instanciar la pestaña únicamente en su primer acceso
        if self.tab_instances[index] is None:
            try:
                tab_class = _load_tab_class(index)
                tab_widget = tab_class()
                self.tab_instances[index] = tab_widget
                container = self.stack.widget(index)
                container.layout().addWidget(tab_widget)
            except Exception as exc:
                logger.exception("Error instanciando pestaña %s: %s", index, exc)
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
        opt_idx = TAB_MODULE_KEYS.index("tab_optimizer")
        self.switch_tab(opt_idx)
        opt_tab = self.tab_instances[opt_idx]
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
        """Fallback: restaura geometría SIEMPRE recortada dentro de una pantalla conectada (FSU-015)."""
        try:
            x, y = int(win["x"]), int(win["y"])
            w, h = int(win["width"]), int(win["height"])
        except (KeyError, TypeError, ValueError):
            return
        if w < 400 or h < 300:
            return

        rect = QRect(x, y, w, h)
        for screen in QGuiApplication.screens():
            avail = screen.availableGeometry()
            if rect.intersects(avail):
                width = min(rect.width(), avail.width())
                height = min(rect.height(), avail.height())
                cx = max(avail.left(), min(rect.x(), avail.right() - width + 1))
                cy = max(avail.top(), min(rect.y(), avail.bottom() - height + 1))
                self.setGeometry(QRect(cx, cy, width, height))
                return

        primary = QGuiApplication.primaryScreen()
        avail = primary.availableGeometry() if primary else QRect(0, 0, 1180, 800)
        self.setGeometry(QRect(
            avail.left() + 40,
            avail.top() + 40,
            min(1180, max(400, avail.width() - 80)),
            min(800, max(300, avail.height() - 80)),
        ))

    def restore_session_state(self, fallback_tab: Optional[int] = None) -> None:
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

        # 2. Pestaña activa (si el usuario no pasó un flag explícito por CLI;
        # None = sin --tab, se respeta la sesión guardada)
        if fallback_tab is None and "active_tab" in state:
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
            if mod_data and self.tab_instances[idx] is not None and not isinstance(self.tab_instances[idx], type):
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
            if tab_obj is not None and not isinstance(tab_obj, type):
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
            if tab is not None and not isinstance(tab, type):
                hook = getattr(tab, "shutdown", None) or getattr(tab, "cleanup", None)
                if callable(hook):
                    try:
                        hook()
                    except Exception as exc:
                        logger.warning("Error en shutdown de %s: %s", type(tab).__name__, exc)

        # FASE 1b: Barrera de espera (FSU-002) — verificar terminación efectiva de workers.
        # Las pestañas pueden exponer wait_for_shutdown(timeout_ms) -> bool (contrato opcional).
        still_running = []
        for tab in self.tab_instances:
            if tab is None or isinstance(tab, type):
                continue
            waiter = getattr(tab, "wait_for_shutdown", None)
            if callable(waiter):
                try:
                    if not waiter(2000):
                        still_running.append(type(tab).__name__)
                except Exception as exc:
                    logger.warning("Error en wait_for_shutdown de %s: %s", type(tab).__name__, exc)
        if still_running:
            logger.warning("Workers no detenidos tras el cierre: %s", ", ".join(still_running))

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
    parser.add_argument("--tab", type=str, default=None, help="Pestaña inicial (reboot, optimizer, cleaner, mcp, radar, apis, diag)")
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
    # None = no se especificó --tab: se respeta la pestaña activa de la sesión guardada.
    init_tab = tab_map.get(args.tab.lower()) if args.tab else None

    # Preflight de dependencias (BUG-08 Grok): PyQt6 es crítico; el resto son advertencias.
    import importlib
    _missing = []
    try:
        importlib.import_module("PyQt6")
    except ImportError:
        _missing.append("PyQt6")
    if _missing:
        print("❌ Dependencia crítica faltante: " + ", ".join(_missing))
        print("   Ejecuta:  ./install.sh")
        sys.exit(1)
    _warnings = []
    for _mod, _label in (("psutil", "psutil"), ("yaml", "PyYAML")):
        try:
            importlib.import_module(_mod)
        except ImportError:
            _warnings.append(_label)
    if _warnings:
        print("⚠️ Advertencia: módulos opcionales ausentes: " + ", ".join(_warnings))
        print("   Algunas pestañas (Cleaner/API) requieren:  pip install " + " ".join(_warnings))

    # Política HiDPI explícita (BUG-08 Grok / FSU-016): debe configurarse estrictamente ANTES de instanciar QApplication.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyleSheet(FLOYDIA_SUITE_QSS)
    
    window = FloydIASuiteApp(initial_tab=init_tab)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
