#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Bootstrap portable de rutas y parser de .env.

Objetivo: eliminar las rutas personales hardcodeadas del codigo fuente del repo
publico. El directorio SCRIPTS del workspace del operador es una dependencia
opcional: si existe, se usa su env_loader canonico; si no (clon limpio del repo
publico), se usa el parser local equivalente.

Invariante: ningun path absoluto del usuario puede aparecer en este repositorio.
"""
import os
import sys

#: Nombre del directorio SCRIPTS dentro del workspace del operador.
SCRIPTS_DIRNAME = "SCRIPTS"

#: Variable de entorno que permite puntear al workspace del operador.
WORKSPACE_ENV_VAR = "FLOYDIA_WORKSPACE"


def candidate_scripts_dirs():
    """Itera directorios SCRIPTS candidatos, del mas especifico al mas generico.

    Orden:
      1. $FLOYDIA_WORKSPACE/SCRIPTS (configuracion explicita).
      2. Walking-up desde la raiz del repo: <repo>/.., <repo>/../.., ...
         Permite localizar el workspace en cualquier layout (FLOYDIA/PUBLIC_REPOS/...).
    """
    env_ws = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    if env_ws:
        yield os.path.join(env_ws, SCRIPTS_DIRNAME)

    cur = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    while cur and cur != os.path.dirname(cur):
        yield os.path.join(cur, SCRIPTS_DIRNAME)
        cur = os.path.dirname(cur)


def find_workspace_root():
    """Raiz del workspace del operador.

    Orden: $FLOYDIA_WORKSPACE -> upward search (SCRIPTS/ o .env) -> raiz del repo.
    Nunca devuelve una ruta absoluta de un usuario concreto.
    """
    env_ws = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    if env_ws and os.path.isdir(env_ws):
        return env_ws
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cur = repo_root
    while cur and cur != os.path.dirname(cur):
        if os.path.isdir(os.path.join(cur, SCRIPTS_DIRNAME)) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return repo_root


def scripts_dir():
    """Directorio SCRIPTS resuelto (o '' si el workspace no tiene SCRIPTS/)."""
    return os.path.join(find_workspace_root(), SCRIPTS_DIRNAME)


def ensure_scripts_on_path():
    """Inserta el primer SCRIPTS existente en sys.path. Devuelve la ruta o ''."""
    for d in candidate_scripts_dirs():
        if d and os.path.isdir(d):
            if d not in sys.path:
                sys.path.insert(0, d)
            return d
    return ""


def env_value(raw):
    """Limpia el valor de una asignacion `KEY=VALUE` tolerando comentarios inline.

    - `KEY="v" # comentario`  -> `v`
    - `KEY=v # comentario`    -> `v`
    - `KEY='v'`               -> `v`
    - `KEY=v#nospace`         -> `v#nospace` (shell no trata '#' sin espacio)
    """
    s = raw.strip()
    if not s:
        return ""
    if s[0] in "\"'":
        quote = s[0]
        end = s.find(quote, 1)
        if end != -1:
            return s[1:end]
        return s[1:]
    for i, ch in enumerate(s):
        if ch == "#" and i > 0 and s[i - 1] in " \t":
            return s[:i].rstrip()
    return s


def env_line(raw):
    """Devuelve (clave, valor_limpio) de una linea `KEY=VALUE`.

    Si la linea no es una asignacion valida devuelve ('', '').
    """
    s = raw.strip()
    if not s or s.startswith("#"):
        return "", ""
    if s.startswith("export "):
        s = s[7:].lstrip()
    if "=" not in s:
        return "", ""
    k, v = s.split("=", 1)
    k = k.strip()
    if not k or not (k[0].isalpha() or k[0] == "_"):
        return "", ""
    return k, env_value(v)


def resolve_env_line():
    """Devuelve la funcion env_line canonica del workspace, o la local si no existe."""
    ensure_scripts_on_path()
    try:
        from env_loader import env_line as _canon  # type: ignore
        return _canon
    except Exception:
        return env_line
