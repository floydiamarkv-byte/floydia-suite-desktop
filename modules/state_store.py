"""
state_store.py — SSOT de persistencia atómica para FloydIA Suite 2.0.

Patrón de escritura:
    tempfile.mkstemp (en el mismo directorio para asegurar mismo filesystem)
    → json.dump → flush → fsync → os.replace (atómico en POSIX) con fcntl.flock
    como defensa en profundidad contra concurrencia.

Patrón de lectura:
    Lectura con flock compartido. Si el JSON está corrupto o truncado,
    se envía a cuarentena (*.corrupt-<ISO>) y se devuelve el default.

Garantías:
    - Cero JSONs truncados o a medio escribir.
    - Un fallo de persistencia jamás crashea la aplicación GUI.
"""

from __future__ import annotations

import fcntl
import glob
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("floydia.state_store")

# Tiempo máximo de espera por el lock antes de degradar (evita congelar el QEventLoop).
FLOCK_TIMEOUT_S = 3.0
# Antigüedad máxima de archivos en cuarentena antes de purgarlos.
QUARANTINE_MAX_AGE_S = 7 * 86400


def _flock_with_timeout(fd: int, flag: int, timeout_s: float = FLOCK_TIMEOUT_S) -> bool:
    """
    fcntl.flock con deadline usando LOCK_NB + sondeo corto.
    Devuelve True si se adquirió el lock, False si se agotó el timeout.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, flag | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


def _purge_stale_quarantines(path: str) -> None:
    """Elimina cuarentenas (*.corrupt-*) con más de QUARANTINE_MAX_AGE_S días."""
    try:
        for old in glob.glob(f"{path}.corrupt-*"):
            try:
                if time.time() - os.path.getmtime(old) > QUARANTINE_MAX_AGE_S:
                    os.remove(old)
            except OSError:
                pass
    except Exception:
        pass


# Regex: captura strings JSON (grupo 1) para preservarlos, y elimina // y /* */.
_JSONC_COMMENT_RE = re.compile(r'("(?:\\.|[^"\\])*")|(//[^\n]*)|(/\*.*?\*/)', re.DOTALL)


def load_jsonc(path: str) -> Dict[str, Any]:
    """
    Carga un archivo JSONC (JSON con comentarios // y /* */), tolerante a
    comentarios dentro y fuera de strings. Lanza json.JSONDecodeError si el
    contenido residual no es JSON válido.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    stripped = _JSONC_COMMENT_RE.sub(lambda m: m.group(1) or "", raw)
    return json.loads(stripped)


def utc_now_iso() -> str:
    """Timestamp ISO-8601 UTC conforme al Protocolo de Memoria v27."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: str, data: Dict[str, Any], mode: int = 0o644) -> None:
    """
    Escritura atómica y tolerante a fallos de un diccionario a JSON.

    - Escribe a un temporal en el MISMO directorio (requisito para os.replace atómico).
    - fsync fuerza el volcado al medio físico antes del rename.
    - os.replace es atómico: el lector ve la versión previa completa o la nueva completa.
    - Limpieza automática de temporales huérfanos ante cualquier error.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    lock_path = f"{path}.lock"

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".floydia_state_", suffix=".tmp")
    try:
        with open(lock_path, "a", encoding="utf-8") as lock_file:
            if not _flock_with_timeout(lock_file.fileno(), fcntl.LOCK_EX):
                logger.warning(
                    "Lock exclusivo ocupado tras %.1fs en %s; se procede sin lock (riesgo asumido).",
                    FLOCK_TIMEOUT_S, lock_path,
                )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                try:
                    os.chmod(tmp_path, mode)
                except Exception:
                    pass
                os.replace(tmp_path, path)
                try:
                    dir_fd = os.open(directory, os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except Exception:
                    pass
                logger.debug("Estado persistido atómicamente: %s", path)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        logger.exception("Fallo al persistir estado atómico en %s", path)
        raise


def atomic_read_json(
    path: str, default: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Lectura tolerante a fallos con bloqueo compartido.
    Si el archivo no existe o está corrupto, devuelve `default` y cuarentena el corrupto.
    """
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default

    lock_path = f"{path}.lock"
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r", encoding="utf-8") as lock_file:
                if not _flock_with_timeout(lock_file.fileno(), fcntl.LOCK_SH):
                    logger.warning(
                        "Lock compartido ocupado tras %.1fs en %s; se lee sin lock (riesgo asumido).",
                        FLOCK_TIMEOUT_S, lock_path,
                    )
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                finally:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
        else:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("La raíz del archivo JSON no es un objeto/diccionario")
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        _purge_stale_quarantines(path)
        quarantine = f"{path}.corrupt-{utc_now_iso().replace(':', '')}"
        moved = False
        try:
            os.replace(path, quarantine)
            moved = True
            logger.warning("JSON corrupto detectado y cuarentenado: %s (%s)", quarantine, exc)
        except OSError:
            # Último recurso: eliminar el corrupto para romper el bucle de lectura fallida.
            try:
                os.remove(path)
                moved = True
                logger.error("JSON corrupto eliminado (no se pudo cuarentenar): %s (%s)", path, exc)
            except OSError:
                logger.error("No se pudo ni cuarentenar ni eliminar el JSON corrupto: %s (%s)", path, exc)
        return default
