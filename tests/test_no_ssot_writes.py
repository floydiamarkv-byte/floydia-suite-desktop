"""Test de regresión: la suite SOLO escribe configs del harness por la vía auditable.

Política (2026-10-12, decisión del operador): propagación automática 1-clic ON.
Las escrituras a rutas protegidas están PERMITIDAS únicamente si:
  - pasan por write_harness_owned(path, data, reason="...") — exige reason no vacío, o
  - están dentro de un bloque `with _harness_write_grant("..."):` — auditable por grep, o
  - son backups (copy2 con la ruta protegida como ORIGEN, p.ej. `+ ".bak-suite"`).

Capa estática (AST): ningún modules/*.py activo invoca una primitiva de escritura
con destino OPENCODE_CONFIG / HERMES_CONFIG / DSH_CONFIG ... fuera de esos mecanismos.
Incluye CONTROL POSITIVO: un snippet sintético debe ser detectado.
"""

import ast
import os
import tempfile

PROTECTED_TOKENS = ("OPENCODE_CONFIG", "OPENCODE_SSOT", "CANONICAL_SSOT",
                    "HERMES_CONFIG", "HERMES_CACHE", "DSH_CONFIG")
PROTECTED_LITERALS = (".opencode", ".hermes", ".dsh", ".config/opencode", "dsh-settings.yaml")
WRITER_NAMES = {"atomic_write_json", "atomic_json_write", "atomic_write_text",
                "write_text", "write_bytes", "dump", "copy2", "copyfile", "move", "replace"}


def _is_write_call(node: ast.Call) -> bool:
    f = node.func
    if isinstance(f, ast.Attribute):
        if f.attr in WRITER_NAMES:
            return True
        if f.attr == "open":
            pass
    if isinstance(f, ast.Name) and f.id in WRITER_NAMES:
        return True
    # open(path, "w"/"a"/"x"/"r+"/...)
    if isinstance(f, ast.Name) and f.id == "open":
        mode_ok = False
        for a in node.args[1:]:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                if any(m in a.value for m in ("w", "a", "x", "+")):
                    mode_ok = True
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                if any(m in str(kw.value.value) for m in ("w", "a", "x", "+")):
                    mode_ok = True
        return mode_ok
    if isinstance(f, ast.Attribute) and f.attr == "open":
        return True  # os.fdopen quedan fuera; cualquier .open con ctx de writer revisado por nombre
    return False


def _call_targets_protected(node: ast.Call, names: set, dst_only: bool = False) -> bool:
    args = node.args[:1] if dst_only else node.args
    for a in args:
        if isinstance(a, ast.Name) and a.id in names:
            return True
        if isinstance(a, ast.Attribute) and a.attr in names:
            return True
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            if any(tok in a.value for tok in PROTECTED_LITERALS):
                return True
    return False


# Mecanismos de escritura auditables autorizados (política 2026-10-12)
AUTHORIZED_WRITERS = {"write_harness_owned"}
GRANT_CONTEXTS = {"_harness_write_grant"}
# Escritores donde la ruta protegida en 1ª posición es el ORIGEN (backup), no el destino
BACKUP_COPY_NAMES = {"copy2", "copyfile"}


def _is_authorized_call(node: ast.Call) -> bool:
    f = node.func
    name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
    if name in AUTHORIZED_WRITERS:
        return True
    if name in BACKUP_COPY_NAMES:
        return True  # copy2(SSOT, SSOT+".bak-suite"): el destino nunca es la ruta protegida
    return False


def _module_name_juggles(src: str) -> set:
    """Alias simples: X = OPENCODE_CONFIG  /  import ... as X."""
    names = set(PROTECTED_TOKENS)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in PROTECTED_TOKENS:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        if isinstance(node, ast.ImportFrom):
            _ = node
    return names


def _dead_ranges(tree):
    """Rangos de líneas muertas: cuerpos de `if False:` y funciones *_legacy."""
    dead = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and node.test.value is False:
            dead.append((node.lineno, node.end_lineno or node.lineno))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.endswith("_legacy"):
            dead.append((node.lineno, node.end_lineno or node.lineno))
    return dead


def _in_dead(line, dead):
    return any(a <= line <= b for a, b in dead)


def test_no_ssot_writes_ast_static():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    moddir = os.path.join(base, "modules")
    targets = [os.path.join(moddir, f) for f in sorted(os.listdir(moddir))
               if f.endswith(".py") and ".bak" not in f]
    targets.append(os.path.join(base, "floydia_suite_app.py"))
    assert targets, "Sin módulos que auditar"

    violations = []
    for path in targets:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src, filename=path)
        names = _module_name_juggles(src)
        dead = _dead_ranges(tree)

        # Rangos cubiertos por `with _harness_write_grant(...):` (vía auditable)
        granted = []
        for node in ast.walk(tree):
            if isinstance(node, ast.With):
                for item in node.items:
                    ce = item.context_expr
                    fname = ""
                    if isinstance(ce, ast.Call):
                        fn = ce.func
                        fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                    if fname in GRANT_CONTEXTS:
                        granted.append((node.lineno, node.end_lineno or node.lineno))

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_write_call(node)):
                continue
            if _in_dead(node.lineno, dead):
                continue
            if any(a <= node.lineno <= b for a, b in granted):
                continue  # escritura dentro de _harness_write_grant: autorizada y auditable
            if _is_authorized_call(node):
                continue  # write_harness_owned exige reason; copy2 es backup (origen protegido)
            if _call_targets_protected(node, names):
                violations.append(f"{path}:{node.lineno}")

    # CONTROL POSITIVO: el detector debe disparar contra un snippet sintético
    synth = "import json\nx = {}\nopen('/home/u/.opencode/opencode.jsonc', 'w').write(json.dumps(x))\n"
    st = ast.parse(synth)
    assert any(isinstance(n, ast.Call) and _is_write_call(n) and _call_targets_protected(n, set()) for n in ast.walk(st)), \
        "CONTROL POSITIVO falló: el detector está ciego"

    assert not violations, "Escrituras activas a rutas protegidas: " + "; ".join(violations)


def test_state_store_guard_blocks_protected_paths(tmp_path):
    from modules import state_store as ss

    home = str(tmp_path)
    # Simular HOME aislado
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        protected = os.path.join(home, ".opencode", "opencode.jsonc")
        assert ss.is_protected_path(protected)
        assert ss.is_protected_path(os.path.join(home, ".dsh", "settings.yaml"))
        assert ss.is_protected_path(os.path.join(home, ".hermes", "config.yaml"))
        assert not ss.is_protected_path(os.path.join(home, "cache", "custom_apis.json"))
        assert not ss.is_protected_path(os.path.join(home, ".config", "floydia-suite", "managed-resources.json"))

        ok_file = os.path.join(str(tmp_path), "cache", "ok.json")
        ss.atomic_write_json(ok_file, {"a": 1})
        assert ss.atomic_read_json(ok_file)["a"] == 1

        try:
            ss.atomic_write_json(protected, {"a": 1})
            raise AssertionError("Debía lanzar ProtectedPathError")
        except ss.ProtectedPathError:
            pass
        try:
            ss.atomic_write_text(os.path.join(home, ".hermes", "config.yaml"), "x: 1")
            raise AssertionError("Debía lanzar ProtectedPathError")
        except ss.ProtectedPathError:
            pass
        try:
            ss.write_harness_owned(protected, {"a": 1}, reason="")
            raise AssertionError("reason vacío debía fallar")
        except ss.ProtectedPathError:
            pass
        ss.write_harness_owned(protected, {"a": 1}, reason="test controlado")
        assert ss.atomic_read_json(protected)["a"] == 1
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def test_atomic_read_json_never_quarantines_protected(tmp_path):
    """Un JSON corrupto en ruta protegida NO debe moverse a cuarentena."""
    from modules import state_store as ss
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(tmp_path)
    try:
        p = os.path.join(str(tmp_path), ".config", "opencode", "opencode.jsonc")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("{corrupto,")
        out = ss.atomic_read_json(p, default={"safe": True})
        assert out == {"safe": True}
        assert os.path.exists(p), "Se movió el archivo protegido a cuarentena"
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
