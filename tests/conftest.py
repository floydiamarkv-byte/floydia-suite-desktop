"""Pytest fixtures compartidos para FloydIA Suite 2.0."""
import os
import sys

import pytest

SUITE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_ROOT not in sys.path:
    sys.path.insert(0, SUITE_ROOT)


@pytest.fixture
def sandboxed_registry(tmp_path, monkeypatch):
    """Aísla el Ownership Registry en un archivo temporal (sin tocar la home del usuario)."""
    import modules.state_store as ss
    reg_file = tmp_path / "managed-resources.json"
    monkeypatch.setattr(ss, "MANAGED_RESOURCES_FILE", str(reg_file))
    return ss, str(reg_file)


@pytest.fixture
def suite_root():
    return SUITE_ROOT