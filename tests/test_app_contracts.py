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


def test_hp45_propagation_purged():
    """Valida que la réplica HP45 haya sido purgada de módulos según especificación."""
    import modules.tab_api_manager as tam
    import modules.tab_radar as tradar
    assert getattr(tam, "SYNC_HP45_ENABLED", None) is False
    assert not hasattr(tradar, "SyncHP45Worker"), "SyncHP45Worker debe ser eliminado de tab_radar"


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


def test_diag_targets_and_ui_widgets_match():
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    _qapp = QApplication.instance() or QApplication([])
    import modules.tab_diagnostics as td
    diag_tab = td.TabDiagnostics()
    try:
        targets = td.get_diag_targets()
        # Todas las claves de los targets deben tener su widget correspondiente en UI
        for key in targets:
            assert key in diag_tab.net_widgets, f"Clave '{key}' de get_diag_targets() ausente en net_widgets"
    finally:
        diag_tab.cleanup()


def test_ping_parser_spanish_and_english(monkeypatch):
    import subprocess
    import modules.tab_diagnostics as td

    # Simular salida ping en español
    sample_es = (
        "PING 192.168.1.1 (192.168.1.1) 56(84) bytes de datos.\n"
        "64 bytes desde 192.168.1.1: icmp_seq=1 ttl=64 tiempo=0.45 ms\n"
    )
    # Simular salida ping en inglés
    sample_en = (
        "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
        "64 bytes from 8.8.8.8: icmp_seq=1 ttl=112 time=24.3 ms\n"
    )

    class MockCompletedProcess:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MockCompletedProcess(sample_es))
    key, res = td._probe_single_target("router", "Router", "192.168.1.1")
    assert res["alive"] is True
    assert "0.45 ms" in res["lat"]

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MockCompletedProcess(sample_en))
    key, res = td._probe_single_target("internet", "Google DNS", "8.8.8.8")
    assert res["alive"] is True
    assert "24.3 ms" in res["lat"]


def test_tab_reboot_dry_run_and_real_mode(monkeypatch):
    """Verifica que el motor de tab_reboot diferencie entre simulación y modo real."""
    import modules.tab_reboot as tr

    dummy_node = {
        "id": "test_node",
        "name": "Nodo de Prueba",
        "type": "localhost",
        "default_ip": "127.0.0.1"
    }
    logs_dry = []
    ok_dry, msg_dry = tr.engine.execute_reboot_node(
        dummy_node, {}, dry_run=True, log_cb=lambda m, lvl: logs_dry.append((m, lvl))
    )
    assert ok_dry is True
    assert any("[SIMULACIÓN DRY-RUN]" in m for m, _ in logs_dry)

    # Simular comando exitoso en modo real sin apagar la máquina
    class MockRebootProcess:
        returncode = 0
        stderr = ""
        stdout = "reboot ok"

    class MockPopen:
        returncode = 0
        def communicate(self, timeout=None):
            return "reboot ok", ""
        def kill(self):
            pass

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MockRebootProcess())
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: MockPopen())
    if hasattr(tr.engine, "subprocess"):
        monkeypatch.setattr(tr.engine.subprocess, "run", lambda *a, **kw: MockRebootProcess())
        monkeypatch.setattr(tr.engine.subprocess, "Popen", lambda *a, **kw: MockPopen())

    logs_real = []
    ok_real, msg_real = tr.engine.execute_reboot_node(
        dummy_node, {}, dry_run=False, log_cb=lambda m, lvl: logs_real.append((m, lvl))
    )
    assert ok_real is True
    assert any("[MODO REAL]" in m for m, _ in logs_real)