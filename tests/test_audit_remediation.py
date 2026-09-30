#!/usr/bin/env python3
"""
Tests unitarios y de contrato para validar las remediaciones de seguridad y estabilidad
derivadas de la auditoría externa de FloydIA Suite 2.0.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Asegurar que el directorio raíz de la suite esté en el path
SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from modules.tab_mcp_skills import _merge_hermes_mcp_content
from modules.tab_optimizer import terminate_verified_processes
from modules.state_store import atomic_write_json, atomic_write_text, atomic_read_json
from modules.tab_cleaner import is_path_strictly_protected


class TestAuditRemediation(unittest.TestCase):

    def test_dsh_sync_does_not_inject_danger_policy(self):
        """Verifica que el código fuente de sync_mcps_to_dsh no contenga directivas danger-full-access ni policy: never."""
        skills_file = os.path.join(SUITE_DIR, "modules", "tab_mcp_skills.py")
        with open(skills_file, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertNotIn("danger-full-access", code, "Vulnerabilidad P0: se encontró 'danger-full-access' en tab_mcp_skills.py")
        self.assertNotIn("policy: never", code, "Vulnerabilidad P0: se encontró 'policy: never' en tab_mcp_skills.py")

    def test_hermes_merge_preserves_trailing_sections(self):
        """Verifica que _merge_hermes_mcp_content preserve íntegramente las secciones posteriores a mcp_servers."""
        initial_yaml = """# Configuración de Hermes
model: anthropic/claude-3.5-sonnet
temperature: 0.7

mcp_servers:
  custom_server:
    command: /usr/local/bin/my-tool
    args: ["--verbose"]

runtime:
  nofile_soft_limit: 4096
  sandbox: true

logging:
  level: debug
"""
        generated = {
            "new_mcp": [
                "  new_mcp:",
                "    command: npx",
                "    args: [\"-y\", \"new-tool\"]",
            ]
        }
        registry = {"resources": {}}

        merged = _merge_hermes_mcp_content(initial_yaml, generated, registry)

        self.assertIn("custom_server:", merged, "Debe preservar servidores manuales anteriores")
        self.assertIn("new_mcp:", merged, "Debe insertar el nuevo servidor generado")
        self.assertIn("runtime:", merged, "CRÍTICO: Debe preservar la sección 'runtime:' que está después de mcp_servers")
        self.assertIn("nofile_soft_limit: 4096", merged)
        self.assertIn("logging:", merged, "CRÍTICO: Debe preservar la sección 'logging:' que está al final")
        self.assertIn("level: debug", merged)

    def test_terminate_verified_processes_excludes_self_and_parent(self):
        """Verifica que terminate_verified_processes jamás incluya el PID propio ni de su padre en wait_procs ni en kill."""
        my_pid = os.getpid()
        parent_pid = os.getppid()

        proc_self = MagicMock()
        proc_self.pid = my_pid

        proc_parent = MagicMock()
        proc_parent.pid = parent_pid

        proc_target = MagicMock()
        proc_target.pid = 999999

        processes = [proc_self, proc_parent, proc_target]

        with patch("psutil.wait_procs", return_value=([], [])) as mock_wait:
            terminated, errors = terminate_verified_processes(processes, grace_seconds=0.1)

            proc_self.terminate.assert_not_called()
            proc_parent.terminate.assert_not_called()
            proc_target.terminate.assert_called_once()

            called_procs = mock_wait.call_args[0][0]
            called_pids = [p.pid for p in called_procs]
            self.assertNotIn(my_pid, called_pids, "El PID propio NO debe pasarse a wait_procs")
            self.assertNotIn(parent_pid, called_pids, "El PID del padre NO debe pasarse a wait_procs")
            self.assertIn(999999, called_pids)

    def test_state_store_raises_timeout_error_if_flock_fails(self):
        """Verifica que atomic_write_json y atomic_write_text aborten con TimeoutError si el lock está ocupado."""
        with patch("modules.state_store._flock_with_timeout", return_value=False):
            with self.assertRaises(TimeoutError):
                atomic_write_json("/tmp/test_nonexistent_state.json", {"test": 1})

            with self.assertRaises(TimeoutError):
                atomic_write_text("/tmp/test_nonexistent_text.txt", "texto de prueba")

    def test_state_store_does_not_quarantine_on_oserror(self):
        """Verifica que un fallo de lectura por OSError (permisos) NO mueva a cuarentena ni elimine el archivo del usuario."""
        test_path = "/tmp/test_oserror_file.json"
        try:
            with open(test_path, "w") as f:
                f.write('{"valid": "json"}')

            with patch("os.path.exists", return_value=True):
                with patch("builtins.open", side_effect=PermissionError("Acceso denegado")):
                    with patch("os.replace") as mock_replace:
                        with patch("os.remove") as mock_remove:
                            res = atomic_read_json(test_path, default={"fallback": True})
                            self.assertEqual(res, {"fallback": True})
                            mock_replace.assert_not_called()
                            mock_remove.assert_not_called()
        finally:
            if os.path.exists(test_path):
                os.remove(test_path)

    def test_cleaner_is_path_strictly_protected_covers_critical_roots(self):
        """Verifica que is_path_strictly_protected bloquee rutas sensibles del sistema, credenciales y git."""
        sensitive_paths = [
            os.path.expanduser("~/.ssh/id_ed25519"),
            os.path.expanduser("~/.secrets/antigravity.env"),
            os.path.expanduser("~/.gnupg/pubring.kbx"),
            os.path.expanduser("~/.config/opencode/opencode.jsonc"),
            os.path.expanduser("~/.hermes/config.yaml"),
            "/home/tec/Dropbox/ANTIGRAVITY_PROJECTS/.git/config",
            "/home/tec/Dropbox/ANTIGRAVITY_PROJECTS/memory-bank/core/activeContext.md",
            "/etc/shadow",
            "/usr/bin/bash",
        ]

        for path in sensitive_paths:
            self.assertTrue(
                is_path_strictly_protected(path),
                f"La ruta sensible '{path}' DEBE estar estrictamente protegida contra borrado."
            )


if __name__ == "__main__":
    unittest.main()
