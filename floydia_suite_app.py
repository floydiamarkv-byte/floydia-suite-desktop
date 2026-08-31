#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  ⚡ FLOYDIA SUITE 2.0 — Centro Unificado de Comando, SRE y Telemetría IA         ║
║  Ecosistema FloydIA: HP15 (Arch SSOT) ↔ Proxmox CT114 / CT106 ↔ MikroTik         ║
║  Diseño: PyQt6 Modern Dashboard (FLOYDIA V6 Brand System)                        ║
║  Arquitectura: Lazy Loading de Pestañas & Shutdown Determinista                  ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import argparse

# Asegurar que el directorio de la suite esté en el path
SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QFont, QPixmap, QCloseEvent
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
from modules.tab_reboot import TabReboot
from modules.tab_optimizer import TabOptimizer
from modules.tab_mcp_skills import TabMcpSkills
from modules.tab_radar import TabRadar
from modules.tab_api_manager import TabApiManager
from modules.tab_diagnostics import TabDiagnostics


class FloydIASuiteApp(QMainWindow):
    def __init__(self, initial_tab: int = 0):
        super().__init__()
        self.setWindowTitle("FloydIA Suite 2.0 — Centro Unificado de Comando y SRE")
        self.resize(1180, 800)
        self.setMinimumSize(1000, 660)
        
        if ICON_APP and os.path.exists(ICON_APP):
            self.setWindowIcon(QIcon(ICON_APP))

        self.nav_buttons = []
        self.tab_instances = [None] * 6
        self.tab_factories = [
            lambda: TabReboot(),
            lambda: TabOptimizer(),
            lambda: TabMcpSkills(),
            lambda: TabRadar(),
            lambda: TabApiManager(),
            lambda: TabDiagnostics()
        ]
        self.init_ui(initial_tab)

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
            brand_box = QHBoxLayout()
            lbl_logo = QLabel("⚡")
            lbl_logo.setFont(QFont("Inter", 22))
            
            brand_text_box = QVBoxLayout()
            lbl_brand = QLabel("FLOYDIA")
            lbl_brand.setFont(QFont("Inter", 16, QFont.Weight.Bold))
            lbl_brand.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN}; letter-spacing: 1.5px;")
            
            lbl_version = QLabel("SUITE 2.0 UNIFICADA")
            lbl_version.setFont(QFont("Inter", 8, QFont.Weight.Bold))
            lbl_version.setStyleSheet(f"color: {COLOR_SECONDARY_BLUE}; letter-spacing: 0.8px;")
            
            brand_text_box.addWidget(lbl_brand)
            brand_text_box.addWidget(lbl_version)
            
            brand_box.addWidget(lbl_logo)
            brand_box.addLayout(brand_text_box)
            brand_box.addStretch()
            brand_lay.addLayout(brand_box)

        lbl_slogan = QLabel("SRE Governor & AI Orchestrator")
        lbl_slogan.setFont(QFont("Inter", 8))
        lbl_slogan.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-style: italic;")
        brand_lay.addWidget(lbl_slogan)

        sidebar_lay.addWidget(brand_container)
        sidebar_lay.addSpacing(14)

        # Separador visual sutil
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {COLOR_BORDER}; max-height: 1px;")
        sidebar_lay.addWidget(sep)
        sidebar_lay.addSpacing(10)

        # Botones de Navegación
        nav_items = [
            ("🔄 Control & Reboot", 0),
            ("⚡ Optimizador SRE", 1),
            ("🧩 MCPs & Skills", 2),
            ("🛰️ AI Radar & Modelos", 3),
            ("🔑 Gestor de APIs & Keys", 4),
            ("📡 Diagnóstico & Logs", 5),
        ]

        for text, index in nav_items:
            btn = QPushButton(text)
            btn.setProperty("class", "NavBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=index: self.switch_tab(idx))
            sidebar_lay.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_lay.addStretch()

        # Footer del Sidebar
        footer_box = QFrame()
        footer_box.setStyleSheet(f"background-color: #0B111C; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 8px;")
        footer_lay = QVBoxLayout(footer_box)
        footer_lay.setContentsMargins(6, 6, 6, 6)
        footer_lay.setSpacing(2)

        lbl_env = QLabel("🟢 HP15 Arch SSOT")
        lbl_env.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        lbl_env.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        lbl_env.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_proto = QLabel("PROTOCOLO v27 · UID 1000")
        lbl_proto.setFont(QFont("Inter", 8))
        lbl_proto.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lbl_proto.setAlignment(Qt.AlignmentFlag.AlignCenter)

        footer_lay.addWidget(lbl_env)
        footer_lay.addWidget(lbl_proto)
        sidebar_lay.addWidget(footer_box)

        main_layout.addWidget(sidebar)

        # ── 2. ÁREA PRINCIPAL CON CONTENIDO ───────────────────────────────────
        content_container = QWidget()
        content_lay = QVBoxLayout(content_container)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(0)

        # Header Superior
        header_frame = QFrame()
        header_frame.setObjectName("HeaderFrame")
        header_lay = QHBoxLayout(header_frame)
        header_lay.setContentsMargins(18, 12, 18, 12)

        self.lbl_current_title = QLabel("Centro de Control FloydIA Suite 2.0")
        self.lbl_current_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        header_lay.addWidget(self.lbl_current_title)
        header_lay.addStretch()

        btn_fast_clean = QPushButton("🚀 Optimización 1-Clic")
        btn_fast_clean.setObjectName("PrimaryBtn")
        btn_fast_clean.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_fast_clean.clicked.connect(self.quick_clean_action)
        header_lay.addWidget(btn_fast_clean)

        content_lay.addWidget(header_frame)

        # Stack de Pestañas (Contenedores para Lazy Loading)
        self.stack = QStackedWidget()
        for i in range(6):
            container = QWidget()
            c_lay = QVBoxLayout(container)
            c_lay.setContentsMargins(0, 0, 0, 0)
            self.stack.addWidget(container)

        content_lay.addWidget(self.stack)
        main_layout.addWidget(content_container)

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("background-color: #070D14; color: #94A3B8; border-top: 1px solid #1E3A5F; padding: 4px;")
        self.status_bar.showMessage("🟢 FloydIA Suite 2.0 activa. Modo Lazy Loading habilitado (<250ms cold start).")
        self.setStatusBar(self.status_bar)

        # Activar pestaña inicial bajo demanda
        self.switch_tab(initial_tab)

    def switch_tab(self, index: int):
        if not (0 <= index < 6):
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

    def closeEvent(self, event: QCloseEvent):
        """Detiene de forma limpia y cooperativa todos los timers y workers activos al cerrar."""
        for tab in self.tab_instances:
            if tab is not None and hasattr(tab, "cleanup") and callable(tab.cleanup):
                try:
                    tab.cleanup()
                except Exception:
                    pass
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="FloydIA Suite 2.0 — Centro Unificado de Comando")
    parser.add_argument("--tab", type=str, default="0", help="Pestaña inicial (reboot, optimizer, mcp, radar, apis, diag)")
    args = parser.parse_args()

    tab_map = {
        "0": 0, "reboot": 0,
        "1": 1, "optimizer": 1, "opti": 1,
        "2": 2, "mcp": 2, "skills": 2,
        "3": 3, "radar": 3, "ai": 3,
        "4": 4, "apis": 4, "api": 4, "keys": 4,
        "5": 5, "diag": 5, "network": 5
    }
    init_tab = tab_map.get(args.tab.lower(), 0)

    app = QApplication(sys.argv)
    app.setStyleSheet(FLOYDIA_SUITE_QSS)
    
    window = FloydIASuiteApp(initial_tab=init_tab)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
