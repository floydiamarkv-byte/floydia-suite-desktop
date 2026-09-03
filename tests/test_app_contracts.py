"""Tests de contratos de la app (floydia_suite_app.py): lazy import, shutdown y centinela."""
import inspect
import os
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6")

from conftest import SUITE_ROOT


def test_lazy_import_real_in_fresh_interpreter():
    """Importar la app NO debe cargar los módulos de pestañas (FSU-016)."""
    code = (
        "import sys, os\n"
        "sys.path.insert(0, %r)\n"
        "import floydia_suite_app as app\n"
        "assert all(m not in sys.modules for m, _ in app.TAB_SPECS), 'lazy import roto'\n"
        "for i, (m, cls) in enumerate(app.TAB_SPECS):\n"
        "    assert getattr(app._load_tab_class(i), '__name__') == cls\n"
        "print('OK')\n"
    ) % SUITE_ROOT
    env = dict(os.environ)
    res = subprocess.run([sys.executable, "-c", code], cwd=SUITE_ROOT, capture_output=True, text=True, env=env)
    assert res.returncode == 0, res.stderr
    assert "OK" in res.stdout


def test_wait_for_shutdown_contract():
    import modules.tab_reboot as tr
    import modules.tab_radar as tradar
    assert hasattr(tr.TabReboot, "wait_for_shutdown")
    assert hasattr(tradar.TabRadar, "wait_for_shutdown")

    import floydia_suite_app as app
    src = inspect.getsource(app.FloydIASuiteApp.closeEvent)
    assert "wait_for_shutdown" in src
    assert "still_running" in src


def test_initial_tab_sentinel_is_none():
    import floydia_suite_app as app
    sig = inspect.signature(app.FloydIASuiteApp.__init__)
    assert sig.parameters["initial_tab"].default is None


def test_hp45_propagation_constants_defined():
    import modules.tab_api_manager as tam
    assert tam.EXPORT_HP45_KEYS_SCRIPT and tam.SYNC_HP45_SCRIPT


def test_fallback_workspace_root_portable():
    import modules.tab_reboot as tr
    fallback = os.path.dirname(os.path.dirname(os.path.abspath(tr.__file__)))
    assert os.path.isdir(fallback), "fallback find_workspace_root no existe"
    # El invariante real: el CÓDIGO FUENTE no contiene ninguna ruta personal hardcodeada
    src = open(tr.__file__, encoding="utf-8").read()
    assert "/home/tec" not in src.replace("expanduser(", ""), "ruta personal hardcodeada en tab_reboot"


def test_tab_diagnostics_wait_for_shutdown():
    import modules.tab_diagnostics as td
    assert hasattr(td.TabDiagnostics, "wait_for_shutdown"), "TabDiagnostics debe implementar wait_for_shutdown"
    assert callable(getattr(td.TabDiagnostics, "wait_for_shutdown"))


def test_hidpi_policy_before_qapplication():
    import floydia_suite_app as app
    src = inspect.getsource(app.main)
    pos_policy = src.find("setHighDpiScaleFactorRoundingPolicy")
    pos_qapp = src.find("QApplication(sys.argv)")
    assert pos_policy != -1, "setHighDpiScaleFactorRoundingPolicy debe estar presente en main()"
    assert pos_qapp != -1, "QApplication(sys.argv) debe estar presente en main()"
    assert pos_policy < pos_qapp, "setHighDpiScaleFactorRoundingPolicy debe ejecutarse estrictamente ANTES de instanciar QApplication"


def test_switch_tab_stores_widget_instances():
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication, QWidget
    _qapp = QApplication.instance() or QApplication([])
    import floydia_suite_app as app
    win = app.FloydIASuiteApp(initial_tab=0)
    try:
        for idx in range(len(app.TAB_MODULE_KEYS)):
            win.switch_tab(idx)
            tab_obj = win.tab_instances[idx]
            assert tab_obj is not None, f"Pestaña {idx} no fue cargada"
            assert not isinstance(tab_obj, type), f"Pestaña {idx} guardó una clase, no una instancia"
            assert isinstance(tab_obj, QWidget), f"Pestaña {idx} debe ser un QWidget"
    finally:
        win.close()