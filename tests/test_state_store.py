"""Tests de state_store.py: persistencia atómica, cuarentena, purga, JSONC y ownership registry."""
import json
import os

from modules import state_store as ss


def test_atomic_write_read_roundtrip(tmp_path):
    p = tmp_path / "test.json"
    ss.atomic_write_json(str(p), {"a": 1, "nested": {"b": 2}})
    assert ss.atomic_read_json(str(p)) == {"a": 1, "nested": {"b": 2}}


def test_quarantine_corrupt_json(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text('{"truncado": tru', encoding="utf-8")
    res = ss.atomic_read_json(str(p), default={"x": 0})
    assert res == {"x": 0}
    assert not p.exists(), "archivo corrupto no fue movido a cuarentena"
    quarantines = list(tmp_path.glob("corrupt.json.corrupt-*"))
    assert quarantines, "cuarentena no creada"


def test_quarantine_purge_old(tmp_path):
    p = tmp_path / "old.json"
    p.write_text('{"mal": 1', encoding="utf-8")
    ss.atomic_read_json(str(p), default={})
    q = list(tmp_path.glob("old.json.corrupt-*"))[0]
    os.utime(q, (0, 0))  # antiguedad > 7 dias
    p.write_text('{"mal": 2', encoding="utf-8")
    ss.atomic_read_json(str(p), default={})
    # Invariante real: ninguna cuarentena con mtime ancestral (0) permanece.
    remaining_old = [x for x in tmp_path.glob("old.json.corrupt-*") if os.path.getmtime(x) == 0]
    assert not remaining_old, "cuarentena antigua no purgada"


def test_load_jsonc_tolerates_comments(tmp_path):
    p = tmp_path / "opencode.jsonc"
    p.write_text(
        '{\n  // comentario\n  "mcp": {"filesystem": {"type": "local"}}, /* bloque */\n'
        '  "model": "deepseek/deepseek-chat", // otro\n'
        '  "url": "http://ejemplo.com//nocomentario"\n}',
        encoding="utf-8",
    )
    parsed = ss.load_jsonc(str(p))
    assert parsed["mcp"]["filesystem"]["type"] == "local"
    assert parsed["model"] == "deepseek/deepseek-chat"
    assert parsed["url"] == "http://ejemplo.com//nocomentario"


def test_merge_managed_section_preserves_manual(tmp_path, monkeypatch):
    from modules import state_store as ss_mod
    reg_file = tmp_path / "managed.json"
    monkeypatch.setattr(ss_mod, "MANAGED_RESOURCES_FILE", str(reg_file))
    ss_mod.atomic_write_json(
        str(reg_file),
        {"version": 1, "resources": {"opencode": {"managed_names": ["old_srv"]}}},
    )
    reg = ss_mod.load_managed_registry()
    merged, managed_now = ss_mod.merge_managed_section(
        {"old_srv": {"type": "local"}, "user_manual": {"command": ["u"]}},
        {"filesystem": {"command": ["fs"]}},
        "opencode",
        reg,
    )
    assert set(merged.keys()) == {"filesystem", "user_manual"}
    assert merged["user_manual"]["command"] == ["u"]
    assert managed_now == ["filesystem"]
    ss_mod.save_managed_registry(reg)
    on_disk = json.loads(reg_file.read_text(encoding="utf-8"))
    assert on_disk["resources"]["opencode"]["managed_names"] == ["filesystem"]


def test_atomic_write_text(tmp_path):
    p = tmp_path / "config.yaml"
    ss.atomic_write_text(str(p), "a: 1\nb: [x, y]\n")
    assert p.read_text(encoding="utf-8") == "a: 1\nb: [x, y]\n"
    ss.atomic_write_text(str(p), "a: 2\n")
    assert p.read_text(encoding="utf-8") == "a: 2\n"
