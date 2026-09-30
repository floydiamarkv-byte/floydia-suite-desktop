#!/usr/bin/env python3
"""
test_audit_remediation_v2.py — Suite de pruebas de regresión y verificación
para las remediaciones técnicas derivadas de las auditorías senior (Qwen3.7, Claude, GLM, ChatGPT).
Desarrollada íntegramente con la biblioteca estándar `unittest` (sin dependencias externas).
"""

import os
import sys
import time
import fcntl
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from modules import restart_workspace_engine as rwe
from modules import state_store as ss
from modules import telemetry
from modules.tab_cleaner import ActionDelete, is_path_strictly_protected
from theme import CancellableThread, stop_worker


class TestAuditRemediationV2(unittest.TestCase):

    # ── 1. SEGURIDAD P0: SSHPASS NUNCA EN ARGV ───────────────────────────────
    def test_ssh_password_never_in_argv_uses_env(self):
        """P0 (Claude B3 / GLM B-02 / GPT): Verifica que la contraseña SSH jamás viaje en argv."""
        cmd, extra_env = rwe._build_ssh_base("root", "192.168.1.200", "P@ssw0rd_Super_Secreta!", timeout_sec=6)
        cmd_str = " ".join(cmd)
        
        self.assertNotIn("P@ssw0rd_Super_Secreta!", cmd_str, "Vulnerabilidad P0: La contraseña aparece en argv")
        self.assertIn("-e", cmd, "sshpass debe usar el flag -e (lectura de entorno)")
        self.assertNotIn("-p", cmd, "sshpass jamás debe usar el flag -p")
        self.assertEqual(extra_env.get("SSHPASS"), "P@ssw0rd_Super_Secreta!", "SSHPASS debe viajar en el dict de entorno del subproceso")
        self.assertEqual(extra_env.get("LC_ALL"), "C", "Debe forzar LC_ALL=C para paridad de mensajes de desconexión")

    # ── 2. TELEMETRÍA: CIERRE DE DESCRIPTORES Y PURGA 30 DÍAS ─────────────────
    def test_telemetry_connection_lifecycle_closes_fd(self):
        """B2 (Claude): Verifica que _connect() cierre deterministamente la conexión SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "telemetry_test.db")
            with patch.object(telemetry, "TELEMETRY_DB", db_path):
                telemetry.init_db()
                telemetry.record_probe_result({"provider": "google", "id": "gemini-flash", "status": "200_OK"})
                
                # Obtener la conexión usando el context manager
                with telemetry._connect() as conn:
                    saved_conn = conn
                
                # Tras salir del bloque with, la conexión DEBE estar cerrada
                with self.assertRaises(sqlite3.ProgrammingError):
                    saved_conn.execute("SELECT 1")

    def test_telemetry_purges_records_older_than_30_days(self):
        """B-14 (GLM): Verifica que init_db purgue automáticamente registros de más de 30 días."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "telemetry_test.db")
            with patch.object(telemetry, "TELEMETRY_DB", db_path):
                telemetry.init_db()
                now = time.time()
                old_ts = now - (40 * 86400)  # 40 días de antigüedad
                new_ts = now - (5 * 86400)   # 5 días de antigüedad
                
                with telemetry._connect() as conn:
                    conn.execute("INSERT INTO probe_results(ts, provider, model, status) VALUES (?, 'prov1', 'm1', '200_OK')", (old_ts,))
                    conn.execute("INSERT INTO probe_results(ts, provider, model, status) VALUES (?, 'prov2', 'm2', '200_OK')", (new_ts,))
                
                # Ejecutar init_db() que dispara la purga
                telemetry.init_db()
                
                with telemetry._connect() as conn:
                    rows = conn.execute("SELECT ts, provider FROM probe_results").fetchall()
                    self.assertEqual(len(rows), 1, "Debe quedar únicamente el registro reciente")
                    self.assertEqual(rows[0][1], "prov2")

    # ── 3. STORAGE ATÓMICO: PERMISOS 0600 Y RESILIENCIA DE UNLOCK ─────────────
    def test_state_store_atomic_write_json_default_permissions(self):
        """B1 / S3: Verifica que atomic_write_json use permisos 0o600 por defecto."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=True) as tmp:
            tmp_path = tmp.name
        try:
            ss.atomic_write_json(tmp_path, {"clave": "valor"})
            st = os.stat(tmp_path)
            mode = st.st_mode & 0o777
            self.assertEqual(mode, 0o600, f"El archivo debe crearse con permisos 0o600, obtenido: {oct(mode)}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            lock_p = f"{tmp_path}.lock"
            if os.path.exists(lock_p):
                os.remove(lock_p)

    def test_state_store_unlock_oserror_tolerance(self):
        """B6 (Claude): Verifica que un fallo al desbloquear fcntl.flock no enmascare una escritura exitosa."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=True) as tmp:
            tmp_path = tmp.name
        
        orig_flock = fcntl.flock
        call_count = {"count": 0}
        
        def flaky_flock(fd, op):
            if op == fcntl.LOCK_UN:
                call_count["count"] += 1
                raise OSError("Kernel simulated unlock transient error")
            return orig_flock(fd, op)
        
        try:
            with patch("fcntl.flock", side_effect=flaky_flock):
                # No debe lanzar excepción aunque LOCK_UN falle
                ss.atomic_write_json(tmp_path, {"status": "success"})
            
            read_data = ss.atomic_read_json(tmp_path)
            self.assertEqual(read_data, {"status": "success"}, "El archivo debe contener los datos persistidos")
            self.assertGreater(call_count["count"], 0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            lock_p = f"{tmp_path}.lock"
            if os.path.exists(lock_p):
                os.remove(lock_p)

    # ── 4. SANITIZACIÓN CENTRALIZADA DE SECRETOS ──────────────────────────────
    def test_sanitize_sensitive_text_redacts_tokens_and_keys(self):
        """RAD-003 / S4: Verifica la redacción de claves sk-..., Bearer y parámetros sensibles."""
        sample = "Error conectando a https://api.openai.com/v1/chat?api_key=sk-proj-1234567890abcdef12345678 con token Bearer eyJhbGciOiJIUzI1NiIsIn"
        cleaned = ss.sanitize_sensitive_text(sample)
        
        self.assertNotIn("sk-proj-1234567890abcdef12345678", cleaned)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsIn", cleaned)
        self.assertIn("[REDACTED", cleaned)

    # ── 5. CLEANER: PROHIBICIÓN DE RM -RF COMO FALLBACK Y RAÍCES CRÍTICAS ──────
    def test_cleaner_fallback_does_not_use_recursive_rf(self):
        """B5 / S2: Verifica que ante PermissionError el cleaner use rm -f y jamás rm -rf sobre archivos."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            target_path = f.name
        
        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res
        
        try:
            with patch("subprocess.run", side_effect=fake_run):
                with patch("os.remove", side_effect=PermissionError("Acceso denegado")):
                    action = ActionDelete(target_path, search_type="file")
                    list(action.execute(really_delete=True, use_sudo=True))
            
            self.assertTrue(len(calls) > 0, "Debe invocar el comando sudo")
            for call in calls:
                self.assertNotIn("-rf", call, f"CRÍTICO: Se utilizó fallback destructivo recursivo '-rf': {call}")
                self.assertIn("-f", call, "Debe utilizar '-f' no recursivo para archivos simples")
        finally:
            if os.path.exists(target_path):
                os.remove(target_path)

    def test_cleaner_strictly_protected_covers_critical_roots(self):
        """Verifica que is_path_strictly_protected bloquee credenciales, llaves SSH, git y repositorios."""
        home = os.path.expanduser("~")
        protected_samples = [
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".secrets", "antigravity.env"),
            os.path.join(home, ".gnupg", "pubring.kbx"),
            "/home/tec/Dropbox/ANTIGRAVITY_PROJECTS/.git/config",
            "/home/tec/Dropbox/ANTIGRAVITY_PROJECTS/memory-bank/core/activeContext.md",
            "/etc/shadow",
            "/usr/bin/python3",
        ]
        for p in protected_samples:
            self.assertTrue(is_path_strictly_protected(p), f"Ruta crítica {p} DEBE estar estrictamente protegida")

    # ── 6. OPTIMIZER: SUDO -N Y ANTI-PID REUSE ───────────────────────────────
    def test_optimizer_drop_caches_uses_sudo_non_interactive(self):
        """OPT-001: Verifica que tab_optimizer.py utilice sudo -n en drop_caches."""
        optimizer_file = os.path.join(SUITE_DIR, "modules", "tab_optimizer.py")
        with open(optimizer_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        self.assertIn('["sudo", "-n", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"]', content,
                      "drop_caches debe usar obligatoriamente 'sudo -n' no interactivo")

    # ── 7. THEME: CONTRATO DE CONCURRENCIA WAIT_OR_CANCEL Y STOP_WORKER ──────
    def test_theme_wait_or_cancel_contract(self):
        """B-09 (GLM): Verifica que wait_or_cancel ejecute cancel() y luego wait()."""
        worker = CancellableThread()
        with patch.object(worker, "cancel") as mock_cancel:
            with patch.object(worker, "wait", return_value=True) as mock_wait:
                res = worker.wait_or_cancel(1.5)
                self.assertTrue(res)
                mock_cancel.assert_called_once()
                mock_wait.assert_called_once_with(1500)

    def test_theme_stop_worker_returns_boolean_status(self):
        """B4 (Claude): Verifica que stop_worker retorne True al detenerse o False si expira."""
        # Worker que finaliza correctamente
        mock_worker_ok = MagicMock()
        mock_worker_ok.isRunning.return_value = True
        mock_worker_ok.wait.return_value = True
        self.assertTrue(stop_worker(mock_worker_ok, timeout_ms=500))
        
        # Worker bloqueado que falla tras quit + wait
        mock_worker_stuck = MagicMock()
        mock_worker_stuck.isRunning.return_value = True
        mock_worker_stuck.wait.side_effect = [False, False]  # Expira en timeout_ms y en 500ms
        self.assertFalse(stop_worker(mock_worker_stuck, timeout_ms=500))

    # ── 8. PERSISTENCIA LAZY EN FLOYDIA SUITE APP ─────────────────────────────
    def test_app_lazy_session_restoration_logic(self):
        """B-01 (GLM): Verifica que los estados de módulos no instanciados se guarden en buffer y se apliquen."""
        from floydia_suite_app import FloydIASuiteApp
        
        # Simular app sin GUI completa
        app_mock = MagicMock(spec=FloydIASuiteApp)
        app_mock.tab_instances = [None] * 7
        app_mock._pending_module_states = {"tab_cleaner": {"profile": "deep"}}
        
        # Simular instanciación diferida de la pestaña 2 (cleaner)
        tab_cleaner_mock = MagicMock()
        tab_cleaner_mock.restore_state = MagicMock()
        app_mock.tab_instances[2] = tab_cleaner_mock
        
        # Ejecutar método real de aplicación diferida
        FloydIASuiteApp._apply_pending_module_states(app_mock)
        
        tab_cleaner_mock.restore_state.assert_called_once_with({"profile": "deep"})
        self.assertNotIn("tab_cleaner", app_mock._pending_module_states)

    def test_app_main_required_symbols_available(self):
        """Verifica que todos los símbolos requeridos en main() (QTimer, etc.) estén importados y disponibles."""
        import floydia_suite_app
        self.assertTrue(hasattr(floydia_suite_app, "QTimer"), "QTimer debe estar disponible en floydia_suite_app")
        self.assertTrue(callable(floydia_suite_app.main), "main() debe ser invocable")


if __name__ == "__main__":
    unittest.main()
