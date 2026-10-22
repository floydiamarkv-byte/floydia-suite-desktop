#!/usr/bin/env python3
"""
Guard de portabilidad: el codigo de produccion no puede contener rutas
absolutas de una maquina concreta.

Un repo publico con `~/Dropbox/ANTIGRAVITY_PROJECTS/...` o `/home/<user>/...`
hardcodeados no es reproducible en ningun otro equipo y expone la topologia
del operador. La resolucion portable vive en modules/_paths.py
(FLOYDIA_WORKSPACE + upward search).
"""
import glob
import os
import unittest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORBIDDEN = (
    "/home/",
    "Dropbox/ANTIGRAVITY_PROJECTS",
    "ANTIGRAVITY_PROJECTS",
    "C:\\Users\\",
)


def _production_files():
    files = sorted(glob.glob(os.path.join(SUITE_DIR, "modules", "*.py")))
    files += [
        os.path.join(SUITE_DIR, "theme.py"),
        os.path.join(SUITE_DIR, "floydia_suite_app.py"),
    ]
    return [f for f in files if os.path.isfile(f)]


class TestNoPersonalPaths(unittest.TestCase):

    def test_production_code_has_no_personal_paths(self):
        files = _production_files()
        self.assertTrue(files, "no se encontraron ficheros de produccion")
        for path in files:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            for needle in FORBIDDEN:
                self.assertNotIn(
                    needle, src,
                    f"{os.path.relpath(path, SUITE_DIR)} contiene una ruta personal ({needle!r}). "
                    f"Usa modules/_paths.py (find_workspace_root / scripts_dir).",
                )

    def test_paths_module_is_portable(self):
        """modules/_paths.py debe resolver el workspace sin conocer al operador."""
        import sys
        modules_dir = os.path.join(SUITE_DIR, "modules")
        if modules_dir not in sys.path:
            sys.path.insert(0, modules_dir)
        import _paths

        self.assertTrue(_paths.scripts_dir().endswith("SCRIPTS"))
        self.assertTrue(os.path.isabs(_paths.find_workspace_root()))
        # La resolucion no puede depender de una variable de entorno ausente.
        old = os.environ.pop("FLOYDIA_WORKSPACE", None)
        try:
            root = _paths.find_workspace_root()
            self.assertTrue(os.path.isabs(root))
            # Debe resolverse por upward search: el resultado es un directorio real
            # (el workspace del operador o la raiz del repo) y no una ruta inventada.
            self.assertTrue(os.path.isdir(root), f"raiz de workspace inexistente: {root}")
        finally:
            if old is not None:
                os.environ["FLOYDIA_WORKSPACE"] = old

    def test_env_line_parses_like_the_canonical_loader(self):
        import sys
        modules_dir = os.path.join(SUITE_DIR, "modules")
        if modules_dir not in sys.path:
            sys.path.insert(0, modules_dir)
        import _paths

        cases = [
            ('KEY="value"  # comment', ("KEY", "value")),
            ("KEY=value # comment", ("KEY", "value")),
            ("KEY='value'", ("KEY", "value")),
            ("KEY=value#nospace", ("KEY", "value#nospace")),
            ("export KEY=value", ("KEY", "value")),
            ("# KEY=value", ("", "")),
            ("not-an-assignment", ("", "")),
        ]
        for raw, expected in cases:
            self.assertEqual(_paths.env_line(raw), expected, f"env_line fallo con {raw!r}")


if __name__ == "__main__":
    unittest.main()
