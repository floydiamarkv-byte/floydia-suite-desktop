"""Tests de tab_mcp_skills.py: fusión no destructiva de YAML de Hermes (FSU-008)."""
import pytest

pytest.importorskip("PyQt6")

from modules import state_store as ss  # noqa: E402
from modules import tab_mcp_skills as tms  # noqa: E402

HERMES_SAMPLE = (
    "font_size: 14\n"
    "# ── Servidores MCP (Sincronizado por Floydia Suite) ──\n"
    "mcp_servers:\n"
    "  old_srv:\n"
    "    command: x\n"
    "  user_manual:\n"
    "    command: y\n"
    "    env:\n"
    "      KEEP: 1\n"
)


def test_hermes_merge_preserves_manual_and_drops_disabled(sandboxed_registry):
    reg = ss.load_managed_registry()
    reg.setdefault("resources", {})["hermes"] = {"managed_names": ["old_srv"]}
    generated = {"obsidian": ["  obsidian:", "    command: z"]}
    out = tms._merge_hermes_mcp_content(HERMES_SAMPLE, generated, reg)

    assert "font_size: 14" in out
    assert "old_srv" not in out
    assert "  obsidian:\n    command: z" in out
    assert "user_manual:\n    command: y\n    env:\n      KEEP: 1" in out
    assert "Servidores MCP (Sincronizado" not in out, "marcador duplicado"
    assert reg["resources"]["hermes"]["managed_names"] == ["obsidian"]


def test_hermes_merge_idempotent(sandboxed_registry):
    reg = ss.load_managed_registry()
    reg.setdefault("resources", {})["hermes"] = {"managed_names": ["old_srv"]}
    generated = {"obsidian": ["  obsidian:", "    command: z"]}
    out1 = tms._merge_hermes_mcp_content(HERMES_SAMPLE, generated, reg)
    out2 = tms._merge_hermes_mcp_content(out1, generated, reg)
    assert out1 == out2