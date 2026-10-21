#!/usr/bin/env python3
"""
Guard de contrato para los workflows de CI.

Regresion real: un escalar YAML sin comillas que contenga ': ' (por ejemplo
`run: bash -n x || echo "SKIP: PKGBUILD"`) hace que GitHub rechace el workflow
completo: el run se marca como fallido en 0s y NUNCA ejecuta un job. Por eso el
CI puede estar "en rojo" sin haber corrido un solo test.

Este test parsea los workflows del repo: si el YAML es invalido, el fallo se
detecta en local, antes del push, y no despues de meses de runs rojos.
"""
import glob
import os
import unittest

import yaml

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF_DIR = os.path.join(SUITE_DIR, ".github", "workflows")


class TestCiWorkflowValid(unittest.TestCase):

    def _workflow_files(self):
        files = sorted(
            glob.glob(os.path.join(WF_DIR, "*.yml")) + glob.glob(os.path.join(WF_DIR, "*.yaml"))
        )
        self.assertTrue(files, "no se encontro ningun workflow en .github/workflows")
        return files

    def test_workflows_parse_as_valid_yaml(self):
        for path in self._workflow_files():
            name = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                try:
                    data = yaml.safe_load(fh)
                except yaml.YAMLError as exc:
                    self.fail(f"{name} tiene YAML invalido (GitHub rechazaria el run sin ejecutar jobs): {exc}")
            self.assertIsInstance(data, dict, f"{name} no parsea a un mapping YAML")
            self.assertIn("jobs", data, f"{name} no define la clave 'jobs'")

    def test_every_job_has_runner_and_steps(self):
        for path in self._workflow_files():
            name = os.path.basename(path)
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            for job_name, job in (data.get("jobs") or {}).items():
                self.assertIn("runs-on", job, f"{name}: job '{job_name}' sin 'runs-on'")
                self.assertIn("steps", job, f"{name}: job '{job_name}' sin 'steps'")
                self.assertTrue(job.get("steps"), f"{name}: job '{job_name}' sin steps")

    def test_matrix_covers_supported_pythons(self):
        path = os.path.join(WF_DIR, "ci.yml")
        if not os.path.isfile(path):
            self.skipTest("no hay ci.yml")
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        versions = (
            ((data.get("jobs") or {}).get("test", {}).get("strategy", {}).get("matrix", {}))
            .get("python-version", [])
        )
        self.assertTrue(versions, "ci.yml no declara la matriz de Python")
        for v in ("3.10", "3.11", "3.12"):
            self.assertIn(v, versions, f"Python {v} fuera de la matriz de CI")


if __name__ == "__main__":
    unittest.main()
