#!/usr/bin/env python3
"""
⚡ FLOYDIA SUITE 2.0 — Runner de Pruebas Resiliente & Determinista
Ejecuta la suite de pruebas mediante pytest (si está disponible) o mediante
un runner standalone determinista sin fallar por rutas o conftest.
"""

import sys
import os
import inspect
import tempfile
import shutil
import time
from pathlib import Path

# Garantizar que la raíz de la suite y tests/ estén en sys.path
SUITE_ROOT = os.path.dirname(os.path.abspath(__file__))
if SUITE_ROOT not in sys.path:
    sys.path.insert(0, SUITE_ROOT)

TESTS_DIR = os.path.join(SUITE_ROOT, "tests")
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

# Forzar modo headless para Qt durante las pruebas
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


class SimpleMonkeyPatch:
    """Mock ligero de monkeypatch para el runner standalone."""
    def __init__(self):
        self._setattrs = []

    def setattr(self, target, name, value, raising=True):
        old = getattr(target, name, None)
        self._setattrs.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._setattrs):
            if old is not None:
                setattr(target, name, old)
            else:
                try:
                    delattr(target, name)
                except AttributeError:
                    pass
        self._setattrs.clear()


class DummyPytest:
    """Shim para permitir que tests con pytest.importorskip corran sin pytest instalado."""
    class Skipped(Exception):
        pass

    @staticmethod
    def importorskip(modname, minversion=None):
        import importlib
        try:
            return importlib.import_module(modname)
        except ImportError:
            raise DummyPytest.Skipped(f"Módulo opcional ausente: {modname}")

    @staticmethod
    def fixture(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda f: f

    @staticmethod
    def skip(reason=""):
        raise DummyPytest.Skipped(reason)


def run_with_pytest(args: list[str]) -> int:
    """Invoca pytest con argumentos coherentes."""
    import pytest
    pytest_args = list(args)
    if not pytest_args:
        pytest_args = [TESTS_DIR, "-v"]
    elif not any(a.startswith("tests") or a.endswith(".py") for a in pytest_args):
        pytest_args = [TESTS_DIR] + pytest_args
    return pytest.main(pytest_args)


def run_standalone_tests() -> int:
    """Runner de reserva puramente nativo en Python 3 cuando pytest no esté instalado."""
    print("ℹ️ Pytest no detectado. Ejecutando runner standalone determinista de FloydIA Suite...")
    if "pytest" not in sys.modules or sys.modules["pytest"] is None:
        sys.modules["pytest"] = DummyPytest()
    test_files = sorted(Path(TESTS_DIR).glob("test_*.py"))
    passed = 0
    failed = 0
    skipped = 0
    start_time = time.time()

    for tf in test_files:
        mod_name = tf.stem
        print(f"\n📂 [{mod_name}] ({tf.name}):")
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(mod_name, str(tf))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception as exc:
            print(f"  ❌ Error importando módulo de prueba {tf.name}: {exc}")
            failed += 1
            continue

        test_funcs = [
            (name, func) for name, func in inspect.getmembers(mod, inspect.isfunction)
            if name.startswith("test_")
        ]

        for name, func in test_funcs:
            sig = inspect.signature(func)
            kwargs = {}
            tmp_dir = None
            mp = None

            try:
                # Inyección básica de fixtures comunes (tmp_path, monkeypatch, sandboxed_registry)
                if "tmp_path" in sig.parameters:
                    tmp_dir = tempfile.mkdtemp(prefix="floydia_test_")
                    kwargs["tmp_path"] = Path(tmp_dir)
                if "monkeypatch" in sig.parameters:
                    mp = SimpleMonkeyPatch()
                    kwargs["monkeypatch"] = mp
                if "sandboxed_registry" in sig.parameters:
                    from modules import state_store as ss
                    if tmp_dir is None:
                        tmp_dir = tempfile.mkdtemp(prefix="floydia_test_")
                    reg_file = Path(tmp_dir) / "managed-resources.json"
                    if mp is None:
                        mp = SimpleMonkeyPatch()
                    mp.setattr(ss, "MANAGED_RESOURCES_FILE", str(reg_file))
                    kwargs["sandboxed_registry"] = (ss, str(reg_file))

                func(**kwargs)
                print(f"  ✅ {name} PASSED")
                passed += 1
            except Exception as exc:
                if exc.__class__.__name__ == "Skipped":
                    print(f"  ⏭️ {name} SKIPPED ({exc})")
                    skipped += 1
                else:
                    print(f"  ❌ {name} FAILED: {exc}")
                    failed += 1
            finally:
                if mp:
                    mp.undo()
                if tmp_dir and os.path.exists(tmp_dir):
                    shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed = time.time() - start_time
    print("\n" + "═" * 70)
    print(f"⚡ Resumen Suite FloydIA: {passed} aprobados, {failed} fallidos, {skipped} omitidos ({elapsed:.2f}s)")
    print("═" * 70)
    return 0 if failed == 0 else 1


def main():
    args = sys.argv[1:]
    try:
        import pytest
        sys.exit(run_with_pytest(args))
    except ImportError:
        sys.exit(run_standalone_tests())


if __name__ == "__main__":
    main()
