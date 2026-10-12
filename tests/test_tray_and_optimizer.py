"""Tests para System Tray, modernización visual V6 y calibración de SRE Cleaner."""
import os
import inspect
import pytest
from PIL import Image

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
from PyQt6.QtCore import Qt, QEvent
from conftest import SUITE_ROOT
import floydia_suite_app as app
import theme
import modules.tab_optimizer as opt


def test_system_tray_contract():
    """Valida la integración de QSystemTrayIcon, menú contextual y reactividad a clics."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _qapp = QApplication.instance() or QApplication([])
    win = app.FloydIASuiteApp(initial_tab=0)
    try:
        assert hasattr(win, "tray_icon"), "FloydIASuiteApp debe poseer tray_icon"
        assert isinstance(win.tray_icon, QSystemTrayIcon)
        menu = win.tray_icon.contextMenu()
        assert menu is not None, "El tray_icon debe tener menú contextual configurado"

        actions = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert "Mostrar / Ocultar" in actions, "Falta opción 'Mostrar / Ocultar' en tray menu"
        assert "Ejecutar Limpieza Rápida" in actions, "Falta opción 'Ejecutar Limpieza Rápida' en tray menu"
        assert "Salir" in actions, "Falta opción 'Salir' en tray menu"

        # Validar toggle_window_visibility
        win.show()
        assert win.isVisible()
        win.toggle_window_visibility()
        assert not win.isVisible()
        win.toggle_window_visibility()
        assert win.isVisible()

        # Validar activación por clic izquierdo (Trigger)
        win.hide()
        assert not win.isVisible()
        win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert win.isVisible()

        # Validar intercepción de minimizado a tray
        class MockChangeEvent:
            def type(self):
                return QEvent.Type.WindowStateChange
            def accept(self):
                pass

        win.setWindowState(Qt.WindowState.WindowMinimized)
        win.changeEvent(MockChangeEvent())
        _qapp.processEvents()

    finally:
        win.close()


def test_visual_assets_and_scaling():
    """Valida dimensiones, fidelidad de color FLOYDIA V6 y escalado nítido con SmoothTransformation."""
    icon_path = os.path.join(SUITE_ROOT, "assets", "icon.png")
    logo_path = os.path.join(SUITE_ROOT, "assets", "logo.png")

    assert os.path.exists(icon_path), "assets/icon.png debe existir"
    assert os.path.exists(logo_path), "assets/logo.png debe existir"

    im_icon = Image.open(icon_path)
    assert im_icon.size == (256, 256), f"Icono debe ser 256x256, obtenido {im_icon.size}"
    assert im_icon.mode == "RGBA", "Icono debe ser RGBA"

    im_logo = Image.open(logo_path)
    assert im_logo.size == (512, 512), f"Logo debe ser 512x512, obtenido {im_logo.size}"
    assert im_logo.mode == "RGBA", "Logo debe ser RGBA"

    # Validar paleta V6 en theme.py
    assert theme.COLOR_PRIMARY_CYAN == "#00E5FF", "COLOR_PRIMARY_CYAN debe ser #00E5FF (Cian Neón V6)"
    assert theme.COLOR_BG_DARK == "#0D1117", "COLOR_BG_DARK debe ser #0D1117 (Azul profundo V6)"

    # Validar helper de escalado con SmoothTransformation (requiere QApplication previa)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _qapp = QApplication.instance() or QApplication([])
    pix = theme.load_smooth_pixmap(logo_path, 52, 52)
    assert not pix.isNull(), "load_smooth_pixmap debe retornar pixmap válido"
    assert pix.width() <= 52 and pix.height() <= 52


def test_optimizer_drop_caches_calibration():
    """Valida la calibración de timeout a 10s y la comprobación previa de carga de I/O."""
    dirty_mb, wb_mb, is_heavy = opt.inspect_kernel_io_buffers()
    assert isinstance(dirty_mb, float)
    assert isinstance(wb_mb, float)
    assert isinstance(is_heavy, bool)
    assert dirty_mb >= 0.0
    assert wb_mb >= 0.0

    # Validar contrato en el código fuente de OptimizerWorker
    src = inspect.getsource(opt.OptimizerWorker.run)
    assert "inspect_kernel_io_buffers" in src, "run() debe invocar inspect_kernel_io_buffers"
    assert "timeout=10" in src, "drop_caches debe configurarse con timeout=10"
    assert "excedió el timeout de 10s" in src, "Mensaje de log debe indicar timeout de 10s"
