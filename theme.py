#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Sistema de Diseño, Paleta y Tema QSS (FLOYDIA V6)
"""

import os
import threading
from typing import Optional
from PyQt6.QtCore import QThread

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")

def resolve_app_icon() -> str:
    """Busca y retorna la ruta del icono de la aplicación con prioridad visual."""
    user_icons = os.path.expanduser("~/.local/share/icons")
    candidates = [
        os.path.join(ASSETS_DIR, "icon.svg"),
        os.path.join(ASSETS_DIR, "icon.png"),
        os.path.join(ASSETS_DIR, "logo.png"),
        os.path.join(user_icons, "floydia_icon.png"),
        os.path.join(user_icons, "floydia_suite.png")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return ""

def resolve_sidebar_logo() -> Optional[str]:
    """Busca la mejor imagen de logotipo para la cabecera del sidebar."""
    user_icons = os.path.expanduser("~/.local/share/icons")
    candidates = [
        os.path.join(ASSETS_DIR, "logo.png"),
        os.path.join(ASSETS_DIR, "logo.svg"),
        os.path.join(ASSETS_DIR, "icon.png"),
        os.path.join(user_icons, "floydia_logo.png")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

ICON_APP = resolve_app_icon()
SIDEBAR_LOGO = resolve_sidebar_logo()

# Colores de Marca FLOYDIA V6 (Contrato Oficial Unificado)
COLOR_BG_DARK = "#050911"
COLOR_BG_CARD = "#0C1322"
COLOR_BG_CARD_HOVER = "#101C30"
COLOR_BG_ACTIVE = "#10283D"
COLOR_BORDER = "#1E3A5F"
COLOR_BORDER_FOCUS = "#00F5D4"
COLOR_PRIMARY_CYAN = "#00F5D4"
COLOR_PRIMARY_HOVER = "#20FFE0"
COLOR_SECONDARY_BLUE = "#00BBF9"
COLOR_TEXT_MAIN = "#F5F8F7"
COLOR_TEXT_MUTED = "#A8B3C2"
COLOR_DANGER = "#EF4444"
COLOR_SUCCESS = "#10B981"
COLOR_WARNING = "#F59E0B"

# Colores Temáticos por Proveedor (Taxonomía Multi-Cuenta)
COLOR_PROV_GOOGLE = "#00F5D4"       # Cyan brillante
COLOR_PROV_NVIDIA = "#10B981"       # Verde esmeralda NIM
COLOR_PROV_DEEPSEEK = "#38BDF8"     # Azul cielo DeepSeek
COLOR_PROV_MISTRAL = "#F59E0B"      # Ámbar / Naranja Mistral
COLOR_PROV_OPENROUTER = "#A855F7"   # Púrpura OpenRouter
COLOR_PROV_GROQ = "#EC4899"         # Rosa LPU Groq
COLOR_PROV_ZAI = "#6366F1"          # Índigo Z.AI
COLOR_PROV_ANTHROPIC = "#F97316"    # Naranja cálido Claude
COLOR_PROV_OPENAI = "#22C55E"       # Verde OpenAI
COLOR_PROV_OLLAMA = "#94A3B8"       # Pizarra Homelab
COLOR_PROV_CUSTOM = "#CBD5E1"       # Gris claro Custom

PROVIDER_COLORS = {
    "google": COLOR_PROV_GOOGLE,
    "nvidia": COLOR_PROV_NVIDIA,
    "deepseek": COLOR_PROV_DEEPSEEK,
    "mistral": COLOR_PROV_MISTRAL,
    "openrouter": COLOR_PROV_OPENROUTER,
    "groq": COLOR_PROV_GROQ,
    "z-ai": COLOR_PROV_ZAI,
    "zai": COLOR_PROV_ZAI,
    "anthropic": COLOR_PROV_ANTHROPIC,
    "openai": COLOR_PROV_OPENAI,
    "ollama": COLOR_PROV_OLLAMA,
    "custom": COLOR_PROV_CUSTOM
}

def get_provider_color(provider: str) -> str:
    """Retorna el color temático HEX para el proveedor especificado."""
    if not provider:
        return COLOR_PROV_CUSTOM
    p = provider.lower().strip()
    return PROVIDER_COLORS.get(p, COLOR_PROV_CUSTOM)

def get_account_badge_label(account_tag: str, provider: str = "") -> str:
    """Formatea la etiqueta de cuenta canónica asegurando formato [C1], [C2], etc."""
    tag = (account_tag or "").strip().upper()
    if not tag:
        tag = "C1"
    if not tag.startswith("["):
        tag = f"[{tag}]"
    return tag


class CancellableThread(QThread):
    """Base de worker con cancelación cooperativa y timeout seguro."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def wait_or_cancel(self, seconds: float) -> bool:
        """Espera sin bloquear indefinidamente el shutdown."""
        return self._cancel_event.wait(max(0.0, seconds))


def is_worker_running(worker: Optional[QThread]) -> bool:
    """Comprueba de forma segura si un worker existe y sigue activo sin lanzar RuntimeError si fue eliminado en C++."""
    if worker is None:
        return False
    try:
        return worker.isRunning()
    except RuntimeError:
        return False


def stop_worker(worker: Optional[QThread], timeout_ms: int = 2500) -> None:
    """Detiene un worker de forma determinista y cooperativa sin terminate() destructivo."""
    if not is_worker_running(worker):
        return

    if hasattr(worker, "cancel"):
        try:
            worker.cancel()
        except Exception:
            pass

    try:
        worker.requestInterruption()
        if worker.wait(timeout_ms):
            return
        worker.quit()
        worker.wait(500)
    except Exception:
        pass

FLOYDIA_SUITE_QSS = f"""
QMainWindow {{
    background-color: {COLOR_BG_DARK};
}}

QWidget {{
    color: {COLOR_TEXT_MAIN};
    font-family: 'IBM Plex Sans', 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}}

/* Sidebar de Navegación */
QFrame#Sidebar {{
    background-color: #0E1724;
    border-right: 1px solid {COLOR_BORDER};
    min-width: 230px;
    max-width: 250px;
}}

QFrame#HeaderFrame {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #152638, stop:1 #0B111C);
    border-bottom: 2px solid {COLOR_PRIMARY_CYAN};
    padding: 10px 16px;
}}

/* Botones de Navegación Sidebar */
QPushButton[class="NavBtn"], QPushButton.NavBtn {{
    background-color: transparent;
    color: {COLOR_TEXT_MUTED};
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    font-weight: 600;
    font-size: 12px;
    text-align: left;
}}

QPushButton[class="NavBtn"]:hover, QPushButton.NavBtn:hover {{
    background-color: #16263A;
    color: {COLOR_PRIMARY_CYAN};
}}

QPushButton[class="NavBtn"][active="true"], QPushButton.NavBtn[active="true"] {{
    background-color: #172D44;
    color: {COLOR_PRIMARY_CYAN};
    border-left: 4px solid {COLOR_PRIMARY_CYAN};
    font-weight: 700;
}}

/* Tarjetas Bento */
QFrame[class="CardFrame"], QFrame.CardFrame, QFrame#CardFrame {{
    background-color: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    padding: 10px;
}}

QFrame[class="CardFrame"]:hover, QFrame.CardFrame:hover, QFrame#CardFrame:hover {{
    border: 1px solid {COLOR_PRIMARY_CYAN};
    background-color: {COLOR_BG_CARD_HOVER};
}}

QFrame#NodeCard {{
    background-color: #132232;
    border: 1px solid #1F364D;
    border-radius: 8px;
}}

QFrame#NodeCard:hover {{
    border: 1px solid {COLOR_PRIMARY_CYAN};
    background-color: #162C44;
}}

/* Botones Generales Elásticos y Ergonómicos */
QPushButton {{
    background-color: #1A324A;
    color: {COLOR_TEXT_MAIN};
    border: 1px solid #2B4E73;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: #234363;
    border: 1px solid {COLOR_PRIMARY_CYAN};
    color: {COLOR_PRIMARY_HOVER};
}}

QPushButton#PrimaryBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_PRIMARY_CYAN}, stop:1 #0EBA99);
    color: #0B111C;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 800;
    padding: 7px 14px;
    letter-spacing: 0.3px;
}}

QPushButton#PrimaryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_PRIMARY_HOVER}, stop:1 {COLOR_PRIMARY_CYAN});
    color: #000000;
}}

QPushButton#PrimaryBtn:disabled {{
    background-color: #2A3B4C;
    color: #6B7C8E;
    border: none;
}}

QPushButton#DangerBtn {{
    background-color: #7F1D1D;
    color: #FEE2E2;
    border: 1px solid {COLOR_DANGER};
    border-radius: 6px;
    font-weight: 700;
    font-size: 12px;
    padding: 6px 12px;
}}

QPushButton#DangerBtn:hover {{
    background-color: #991B1B;
    border: 1px solid #F87171;
}}

QPushButton#SecondaryBtn {{
    background-color: #1A2E44;
    color: {COLOR_SECONDARY_BLUE};
    border: 1px solid #2D4C6B;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
    font-size: 11px;
}}

QPushButton#SecondaryBtn:hover {{
    background-color: #223D5B;
    border: 1px solid {COLOR_SECONDARY_BLUE};
    color: #38BDF8;
}}

QPushButton#ArrowBtn {{
    background-color: #1F364D;
    color: {COLOR_PRIMARY_CYAN};
    border: 1px solid #2D4C6B;
    border-radius: 4px;
    padding: 2px 6px;
    font-weight: bold;
    font-size: 11px;
}}

QPushButton#ArrowBtn:hover {{
    background-color: {COLOR_PRIMARY_CYAN};
    color: #0B111C;
}}

/* Botones de Acción Especial y Propagación 1-Clic */
QPushButton#ActionSyncBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #00F5D4);
    color: #050911;
    font-weight: 800;
    font-size: 12px;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
}}

QPushButton#ActionSyncBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34D399, stop:1 #20FFE0);
    color: #000000;
}}

QPushButton#DeepSeekActionBtn {{
    background-color: #0369A1;
    color: #F0F9FF;
    border: 1px solid #38BDF8;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 700;
    font-size: 11px;
}}

QPushButton#DeepSeekActionBtn:hover {{
    background-color: #0284C7;
    border: 1px solid #7DD3FC;
    color: #FFFFFF;
}}

/* Entradas y Textos */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: #070D14;
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {COLOR_PRIMARY_CYAN};
    selection-color: #0B111C;
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {COLOR_PRIMARY_CYAN};
}}

QComboBox {{
    background-color: #132233;
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 12px;
}}

QComboBox:hover {{
    border: 1px solid {COLOR_PRIMARY_CYAN};
}}

QComboBox QAbstractItemView {{
    background-color: #152638;
    color: {COLOR_TEXT_MAIN};
    selection-background-color: #1A3A5A;
    selection-color: {COLOR_PRIMARY_CYAN};
    border: 1px solid {COLOR_BORDER};
}}

/* Tablas y Listas */
QTableWidget {{
    background-color: #080E18;
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    gridline-color: #162638;
    selection-background-color: #17344D;
    selection-color: {COLOR_TEXT_MAIN};
}}

QTableWidget::item {{
    padding: 5px;
    border-bottom: 1px solid #132233;
}}

QTableWidget::item:selected {{
    background-color: #1A3857;
    color: {COLOR_PRIMARY_CYAN};
}}

QHeaderView::section {{
    background-color: #0E1A29;
    color: {COLOR_TEXT_MUTED};
    padding: 6px 10px;
    border: none;
    border-bottom: 2px solid {COLOR_BORDER};
    border-right: 1px solid #132233;
    font-weight: 700;
    font-size: 12px;
}}

QHeaderView::section:hover {{
    background-color: #15273C;
    color: {COLOR_PRIMARY_CYAN};
}}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: #070D14;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background-color: #223D5B;
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_PRIMARY_CYAN};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: #070D14;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: #223D5B;
    min-width: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLOR_PRIMARY_CYAN};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Barras de Progreso */
QProgressBar {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    text-align: center;
    background-color: #070D14;
    color: #FFFFFF;
    font-weight: bold;
    height: 18px;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_PRIMARY_CYAN}, stop:1 {COLOR_SECONDARY_BLUE});
    border-radius: 5px;
}}

/* TabWidget */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_BG_CARD};
    border-radius: 8px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: #0E1A29;
    color: {COLOR_TEXT_MUTED};
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 4px;
    font-weight: 600;
}}

QTabBar::tab:selected {{
    background-color: {COLOR_BG_CARD};
    color: {COLOR_PRIMARY_CYAN};
    border-top: 2px solid {COLOR_PRIMARY_CYAN};
}}

QTabBar::tab:hover:!selected {{
    background-color: #16283D;
    color: {COLOR_TEXT_MAIN};
}}

QCheckBox {{
    spacing: 8px;
    font-weight: 600;
    color: {COLOR_TEXT_MAIN};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #38BDF8;
    background-color: #070D14;
}}

QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY_CYAN};
    border: 1px solid {COLOR_PRIMARY_CYAN};
}}

QRadioButton {{
    spacing: 8px;
    font-weight: 600;
    color: {COLOR_TEXT_MAIN};
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid #38BDF8;
    background-color: #070D14;
}}

QRadioButton::indicator:checked {{
    background-color: {COLOR_PRIMARY_CYAN};
    border: 1px solid {COLOR_PRIMARY_CYAN};
}}
"""
