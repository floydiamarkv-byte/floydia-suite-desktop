#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🧹 FLOYDIA SUITE 2.0 — Pestaña 7: SRE BleachBit Cleaner & System Optimizer      ║
║  Ecosistema FloydIA: Motor de Limpieza Profunda, Seguro y Multi-Perfil          ║
║  Arquitectura: BleachBit Engine (Cleaner/Option/Action) + Dynamic Chromium AST   ║
║  Seguridad: Allowlist Inmutable de Extensiones & Bóvedas de Bitwarden            ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import glob
import json
import time
import shutil
import sqlite3
import fnmatch
import subprocess
from typing import Dict, Any, List, Optional, Tuple, Set, Generator

import psutil
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread, QObject
from PyQt6.QtGui import QFont, QColor, QCursor, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QProgressBar, QPlainTextEdit, QGridLayout,
    QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QLineEdit, QSplitter, QAbstractItemView, QSizePolicy, QInputDialog
)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker
)


def check_sudo_active() -> bool:
    """Comprueba de forma no bloqueante si sudo está habilitado sin solicitar contraseña."""
    try:
        res = subprocess.run(["sudo", "-n", "true"], capture_output=True, check=False)
        return res.returncode == 0
    except Exception:
        return False

# ── 1. CONFIGURACIÓN Y RUTAS SRE ──────────────────────────────────────────────
CURRENT_USER = os.environ.get("USER", "tec")

def find_workspace_root() -> str:
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.exists(os.path.join(curr, ".env")) or os.path.exists(os.path.join(curr, "requirements.txt")):
            return curr
        curr = os.path.dirname(curr)
    return "/home/tec/Dropbox/ANTIGRAVITY_PROJECTS"

WORKSPACE_ROOT = os.environ.get("FLOYDIA_WORKSPACE", find_workspace_root())
CACHE_DIR = os.path.join(WORKSPACE_ROOT, "cache")
ACTION_JOURNAL_FILE = os.path.join(CACHE_DIR, "action_journal.jsonl")


def log_sre_action(action: str, target: Any, result: str, duration_ms: int = 0, detail: str = "") -> None:
    """Registra una acción estructurada en el Action Journal para auditoría."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "module": "tab_cleaner_bleachbit",
        "action": action,
        "target": target,
        "requested_by": CURRENT_USER,
        "result": result,
        "duration_ms": duration_ms,
        "detail": detail
    }
    try:
        with open(ACTION_JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def format_bytes(b: int) -> str:
    """Formatea bytes a KB, MB, GB de forma legible."""
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    else:
        return f"{b / (1024 * 1024 * 1024):.2f} GB"


# ── 2. ALLOWLIST INMUTABLE DE SEGURIDAD (BITWARDEN & EXTENSIONES) ──────────────
# Extension ID oficial de Bitwarden en Chrome Web Store
BITWARDEN_EXTENSION_ID = "nngceckbapebfimnlniiiahkandclblb"

PROTECTED_FOLDER_PATTERNS = [
    "*/Extensions",
    "*/Extensions/*",
    "*/Extension State",
    "*/Extension State/*",
    "*/Extension Rules",
    "*/Extension Rules/*",
    "*/Local Extension Settings",
    "*/Local Extension Settings/*",
    "*/Sync Extension Settings",
    "*/Sync Extension Settings/*",
    "*/IndexedDB/chrome-extension_*",
    "*/Local Storage/leveldb/chrome-extension_*",
    "*/databases/chrome-extension_*",
    f"*{BITWARDEN_EXTENSION_ID}*"
]

PROTECTED_CRITICAL_FILES = [
    "Preferences",
    "Secure Preferences",
    "Login Data",
    "Login Data For Account",
    "Bookmarks",
    "Web Data"  # Contiene perfiles de autocompletado y cuentas
]

def is_path_strictly_protected(path: str) -> bool:
    """
    Evalúa si una ruta está protegida contra cualquier operación de borrado.
    Garantiza que Bitwarden y las extensiones nunca sean alteradas.
    """
    norm = os.path.normpath(path)
    base_name = os.path.basename(norm)

    # 1. Comprobar archivos críticos exactos
    if base_name in PROTECTED_CRITICAL_FILES and not norm.endswith(".tmp"):
        return True

    # 2. Comprobar si contiene el ID de Bitwarden
    if BITWARDEN_EXTENSION_ID in norm:
        return True

    # 3. Comprobar patrones de carpetas de plugins
    for pattern in PROTECTED_FOLDER_PATTERNS:
        if fnmatch.fnmatch(norm, pattern):
            return True

    # 4. Comprobación de segmentos de directorio clave
    parts = norm.split(os.sep)
    critical_segments = {
        "Extensions", "Extension State", "Extension Rules",
        "Local Extension Settings", "Sync Extension Settings"
    }
    if any(seg in critical_segments for seg in parts):
        return True

    return False


# ── 3. ARQUITECTURA DE ACCIONES BLEACHBIT (ACTION ENGINE) ─────────────────────
class BleachAction:
    """Clase base para acciones de limpieza de BleachBit."""
    def __init__(self, description: str):
        self.description = description

    def execute(self, really_delete: bool, use_sudo: bool = False) -> Generator[Tuple[int, str, str], None, None]:
        """
        Ejecuta o previsualiza la acción.
        Yields: (bytes_liberados, ruta_procesada, estado)
        """
        raise NotImplementedError


class ActionDelete(BleachAction):
    """Acción de borrado de archivos o directorios al estilo BleachBit."""
    def __init__(self, path: str, search_type: str = "file", description: str = "Eliminar"):
        super().__init__(description)
        self.path = os.path.expanduser(os.path.expandvars(path))
        self.search_type = search_type  # 'file', 'walk.all', 'walk.files', 'glob'

    def _resolve_paths(self) -> List[str]:
        if self.search_type == "file":
            return [self.path] if os.path.exists(self.path) else []
        elif self.search_type == "glob":
            return glob.glob(self.path, recursive=True)
        elif self.search_type in ("walk.all", "walk.files"):
            if not os.path.exists(self.path):
                return []
            found = []
            if os.path.isfile(self.path):
                return [self.path]
            for root, dirs, files in os.walk(self.path, topdown=False):
                for f in files:
                    found.append(os.path.join(root, f))
                if self.search_type == "walk.all":
                    for d in dirs:
                        found.append(os.path.join(root, d))
            return found
        return []

    def execute(self, really_delete: bool, use_sudo: bool = False) -> Generator[Tuple[int, str, str], None, None]:
        paths = self._resolve_paths()
        for p in paths:
            # 🛡️ COMPROBACIÓN DE ALLOWLIST INMUTABLE
            if is_path_strictly_protected(p):
                yield (0, p, "PROTECTED")
                continue

            try:
                if not os.path.exists(p):
                    continue

                size = 0
                if os.path.isfile(p) or os.path.islink(p):
                    try:
                        size = os.path.getsize(p)
                    except Exception:
                        size = 0

                if really_delete:
                    if os.path.isfile(p) or os.path.islink(p):
                        try:
                            os.remove(p)
                            yield (size, p, "DELETED")
                        except PermissionError:
                            if use_sudo:
                                res = subprocess.run(["sudo", "-n", "rm", "-f", p], capture_output=True, check=False)
                                if res.returncode == 0:
                                    yield (size, p, "DELETED (sudo)")
                                else:
                                    yield (0, p, "PERMISSION_DENIED")
                            else:
                                yield (0, p, "PERMISSION_DENIED")
                    elif os.path.isdir(p) and self.search_type == "walk.all":
                        try:
                            # Solo borrar directorios si están vacíos o al final del walk
                            os.rmdir(p)
                            yield (0, p, "DELETED_DIR")
                        except OSError:
                            if use_sudo:
                                res = subprocess.run(["sudo", "-n", "rmdir", p], capture_output=True, check=False)
                                if res.returncode == 0:
                                    yield (0, p, "DELETED_DIR (sudo)")
                else:
                    # Modo Vista Previa / Dry-Run
                    yield (size, p, "PREVIEW")

            except PermissionError:
                if really_delete and use_sudo:
                    res = subprocess.run(["sudo", "-n", "rm", "-rf", p], capture_output=True, check=False)
                    if res.returncode == 0:
                        yield (size, p, "DELETED (sudo)")
                    else:
                        yield (0, p, "PERMISSION_DENIED")
                else:
                    yield (0, p, "PERMISSION_DENIED")
            except Exception as exc:
                yield (0, p, f"ERROR: {exc}")


class ActionTrashMounts(BleachAction):
    """
    Escanea y limpia papeleras (.recycle, .Trash-*) en puntos de montaje /mnt/*/
    con timeout estricto para evitar congelamientos en sistemas de archivos de red (NFS/CIFS).
    Soporta elevación de privilegios vía sudo.
    """
    def __init__(self, description: str = "Papeleras en /mnt/"):
        super().__init__(description)

    def _get_mount_points(self) -> List[str]:
        """Obtiene montajes en /mnt/ de forma segura comprobando timeouts."""
        mounts = []
        if not os.path.exists("/mnt"):
            return mounts
        try:
            entries = os.listdir("/mnt")
        except Exception:
            return mounts

        for entry in entries:
            mount_path = os.path.join("/mnt", entry)
            # Validar si el montaje responde antes de entrar a fondo (evitar cuelgues NFS)
            try:
                res = subprocess.run(
                    ["timeout", "1.5s", "test", "-d", mount_path],
                    capture_output=True,
                    check=False
                )
                if res.returncode == 0:
                    mounts.append(mount_path)
            except Exception:
                pass
        return mounts

    def execute(self, really_delete: bool, use_sudo: bool = False) -> Generator[Tuple[int, str, str], None, None]:
        mounts = self._get_mount_points()
        for mount in mounts:
            for pattern in [".recycle", ".Trash-*"]:
                try:
                    cmd = ["timeout", "2s", "find", mount, "-maxdepth", "1", "-name", pattern]
                    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if res.returncode != 0:
                        continue
                    trash_paths = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
                except Exception:
                    continue

                for tpath in trash_paths:
                    if is_path_strictly_protected(tpath):
                        yield (0, tpath, "PROTECTED")
                        continue

                    # Obtener tamaño con du y timeout
                    size = 0
                    try:
                        du_cmd = ["timeout", "3s", "du", "-sb", tpath]
                        if use_sudo:
                            du_cmd = ["sudo", "-n"] + du_cmd
                        du_res = subprocess.run(du_cmd, capture_output=True, text=True, check=False)
                        if du_res.returncode == 0 and du_res.stdout.strip():
                            size = int(du_res.stdout.strip().split()[0])
                    except Exception:
                        size = 0

                    if really_delete:
                        deleted = False
                        if use_sudo:
                            del_cmd = ["sudo", "-n", "timeout", "5s", "rm", "-rf", tpath]
                            del_res = subprocess.run(del_cmd, capture_output=True, text=True, check=False)
                            if del_res.returncode == 0:
                                deleted = True
                                yield (size, tpath, "DELETED (sudo)")
                            else:
                                yield (0, tpath, f"ERROR (sudo: {del_res.stderr.strip() or 'falló'})")
                                continue

                        if not deleted:
                            try:
                                shutil.rmtree(tpath)
                                yield (size, tpath, "DELETED")
                            except PermissionError:
                                yield (0, tpath, "PERMISSION_DENIED (Activa Sudo)")
                            except Exception as exc:
                                yield (0, tpath, f"ERROR: {exc}")
                    else:
                        yield (size, tpath, "PREVIEW")


class ActionVacuum(BleachAction):
    """Compactación y desfragmentación de base de datos SQLite sin borrar datos."""
    def __init__(self, db_path: str, description: str = "SQLite VACUUM"):
        super().__init__(description)
        self.db_path = os.path.expanduser(os.path.expandvars(db_path))

    def execute(self, really_delete: bool, use_sudo: bool = False) -> Generator[Tuple[int, str, str], None, None]:
        if not os.path.exists(self.db_path) or not os.path.isfile(self.db_path):
            return

        # 🛡️ Protección
        if is_path_strictly_protected(self.db_path):
            yield (0, self.db_path, "PROTECTED")
            return

        initial_size = os.path.getsize(self.db_path)
        if really_delete:
            try:
                # Conectar y ejecutar VACUUM
                conn = sqlite3.connect(self.db_path, timeout=5.0)
                conn.execute("VACUUM;")
                conn.close()
                final_size = os.path.getsize(self.db_path)
                freed = max(0, initial_size - final_size)
                yield (freed, self.db_path, "VACUUMED")
            except sqlite3.OperationalError as e:
                yield (0, self.db_path, f"LOCKED ({e})")
            except Exception as e:
                yield (0, self.db_path, f"ERROR ({e})")
        else:
            # En preview mostramos que la BD existe y es elegible para compactación
            yield (0, self.db_path, f"VACUUM_PREVIEW ({format_bytes(initial_size)})")


class ActionTruncate(BleachAction):
    """Vacia el contenido de un archivo de log sin borrar el fichero."""
    def __init__(self, path: str, description: str = "Truncar log"):
        super().__init__(description)
        self.path = os.path.expanduser(os.path.expandvars(path))

    def execute(self, really_delete: bool, use_sudo: bool = False) -> Generator[Tuple[int, str, str], None, None]:
        if not os.path.exists(self.path) or not os.path.isfile(self.path):
            return

        if is_path_strictly_protected(self.path):
            yield (0, self.path, "PROTECTED")
            return

        size = os.path.getsize(self.path)
        if really_delete:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.truncate(0)
                yield (size, self.path, "TRUNCATED")
            except Exception as exc:
                yield (0, self.path, f"ERROR: {exc}")
        else:
            yield (size, self.path, "PREVIEW")


class ScriptRunnerWorker(CancellableThread):
    """Ejecuta un script bash y emite su salida línea por línea en tiempo real a la consola."""
    sig_line = pyqtSignal(str, str)
    sig_finished = pyqtSignal(bool, str)

    def __init__(self, script_path: str, use_sudo: bool = False, parent=None):
        super().__init__(parent)
        self.script_path = script_path
        self.use_sudo = use_sudo
        self._proc = None

    def run(self):
        start_time = time.time()
        cmd = ["bash", self.script_path]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in iter(self._proc.stdout.readline, ''):
                if self.is_cancelled():
                    self._proc.terminate()
                    self.sig_line.emit("⏹️ Script cancelado por el usuario.", "warning")
                    break
                stripped = line.rstrip()
                if stripped:
                    lvl = "info"
                    if "TOTAL LIBERADO" in stripped:
                        lvl = "success"
                    elif "ERROR" in stripped or "Permission denied" in stripped:
                        lvl = "error"
                    elif "===" in stripped or "---" in stripped:
                        lvl = "header"
                    self.sig_line.emit(f"  {stripped}", lvl)

            self._proc.stdout.close()
            ret = self._proc.wait()
            duration = time.time() - start_time
            if ret == 0:
                self.sig_line.emit(f"✅ Script finalizado con éxito en {duration:.1f}s.", "success")
                self.sig_finished.emit(True, "Completado")
            else:
                self.sig_line.emit(f"⚠️ Script finalizó con código {ret}.", "warning")
                self.sig_finished.emit(False, f"Código {ret}")

        except Exception as e:
            self.sig_line.emit(f"❌ Error al ejecutar script: {e}", "error")
            self.sig_finished.emit(False, str(e))

    def cancel(self):
        super().cancel()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass


# ── 4. MODELO DE LIMPIADORES Y OPCIONES (CLEANER & OPTIONS) ───────────────────
class CleanerOption:
    def __init__(
        self,
        opt_id: str,
        label: str,
        description: str,
        actions: List[BleachAction],
        default_checked: bool = True,
        is_warning: bool = False,
        warning_msg: str = ""
    ):
        self.opt_id = opt_id
        self.label = label
        self.description = description
        self.actions = actions
        self.default_checked = default_checked
        self.is_warning = is_warning
        self.warning_msg = warning_msg


class CleanerCategory:
    def __init__(self, cat_id: str, label: str, icon: str, description: str):
        self.cat_id = cat_id
        self.label = label
        self.icon = icon
        self.description = description
        self.options: List[CleanerOption] = []

    def add_option(self, option: CleanerOption):
        self.options.append(option)


# ── 5. DESCUBRIMIENTO DINÁMICO MULTI-PERFIL CHROMIUM ──────────────────────────
def discover_chromium_profiles(base_config_dir: str, base_cache_dir: str) -> List[Dict[str, Any]]:
    """
    Descubre dinámicamente todos los perfiles en un navegador Chromium (Chrome / Brave).
    Extrae el nombre legible del perfil desde Preferences o Local State.
    """
    profiles: List[Dict[str, Any]] = []
    if not os.path.exists(base_config_dir):
        return profiles

    # Leer Local State para nombres de perfiles si está disponible
    local_state_file = os.path.join(base_config_dir, "Local State")
    profile_info_cache = {}
    if os.path.exists(local_state_file):
        try:
            with open(local_state_file, "r", encoding="utf-8", errors="ignore") as f:
                ls_data = json.load(f)
                profile_info_cache = ls_data.get("profile", {}).get("info_cache", {})
        except Exception:
            pass

    for entry in os.listdir(base_config_dir):
        if entry == "Default" or entry.startswith("Profile "):
            config_profile_dir = os.path.join(base_config_dir, entry)
            if not os.path.isdir(config_profile_dir):
                continue

            cache_profile_dir = os.path.join(base_cache_dir, entry)

            # Extraer nombre legible
            display_name = entry
            if entry in profile_info_cache:
                info = profile_info_cache[entry]
                name_val = info.get("name")
                email_val = info.get("user_name")
                if name_val and email_val and name_val != email_val:
                    display_name = f"{name_val} ({email_val})"
                elif name_val:
                    display_name = name_val
                elif email_val:
                    display_name = email_val
            else:
                # Intentar leer desde Preferences local
                pref_file = os.path.join(config_profile_dir, "Preferences")
                if os.path.exists(pref_file):
                    try:
                        with open(pref_file, "r", encoding="utf-8", errors="ignore") as pf:
                            p_data = json.load(pf)
                            name_val = p_data.get("profile", {}).get("name")
                            if name_val:
                                display_name = name_val
                    except Exception:
                        pass

            profiles.append({
                "folder_name": entry,
                "display_name": display_name,
                "config_path": config_profile_dir,
                "cache_path": cache_profile_dir
            })

    # Ordenar: Default primero, luego Profile 1..N
    def sort_key(p):
        fn = p["folder_name"]
        if fn == "Default":
            return (0, 0)
        if fn.startswith("Profile "):
            try:
                return (1, int(fn.split()[1]))
            except ValueError:
                return (1, 999)
        return (2, fn)

    profiles.sort(key=sort_key)
    return profiles


def build_chromium_cleaner_category(
    cat_id: str,
    browser_label: str,
    browser_icon: str,
    config_base: str,
    cache_base: str
) -> Optional[CleanerCategory]:
    """Construye un CleanerCategory con soporte multi-perfil para un navegador."""
    config_dir = os.path.expanduser(config_base)
    cache_dir = os.path.expanduser(cache_base)

    if not os.path.exists(config_dir) and not os.path.exists(cache_dir):
        return None

    profiles = discover_chromium_profiles(config_dir, cache_dir)
    if not profiles:
        return None

    cat = CleanerCategory(
        cat_id=cat_id,
        label=f"{browser_label} ({len(profiles)} Perfiles)",
        icon=browser_icon,
        description=f"Limpieza granular multi-perfil de {browser_label}. Extensiones y Bitwarden 100% blindados."
    )

    # 1. Opciones Globales del Navegador (Caché Base / Crash Reports)
    global_actions = [
        ActionDelete(os.path.join(config_dir, "Crashpad"), "walk.all", "Crashpad global"),
        ActionDelete(os.path.join(config_dir, "Crash Reports"), "walk.all", "Crash Reports global"),
        ActionDelete(os.path.join(config_dir, "component_crx_cache"), "walk.all", "Component CRX Cache"),
        ActionDelete(os.path.join(config_dir, "GraphiteDawnCache"), "walk.all", "Graphite Dawn Cache"),
        ActionDelete(os.path.join(config_dir, "GrShaderCache"), "walk.all", "GrShader Cache"),
        ActionDelete(os.path.join(config_dir, "ShaderCache"), "walk.all", "Shader Cache global")
    ]
    cat.add_option(CleanerOption(
        opt_id=f"{cat_id}__global_cache",
        label="🌐 Caché Global & Crashpad del Sistema",
        description="Elimina informes de fallos y caché compartida de shaders de la aplicación.",
        actions=global_actions,
        default_checked=True
    ))

    # 2. Opciones por cada Perfil Detectado
    for p in profiles:
        fn = p["folder_name"]
        dn = p["display_name"]
        cp = p["config_path"]
        cached = p["cache_path"]

        # 2.1 Caché Web Principal & Code Cache
        web_cache_actions = [
            ActionDelete(os.path.join(cached, "Cache"), "walk.all", "Caché HTTP"),
            ActionDelete(os.path.join(cached, "Code Cache"), "walk.all", "Code Cache JS/Wasm"),
            ActionDelete(os.path.join(cached, "image_cache"), "walk.all", "Image Cache"),
            ActionDelete(os.path.join(cp, "Cache"), "walk.all", "Caché de perfil"),
            ActionDelete(os.path.join(cp, "Code Cache"), "walk.all", "Code Cache de perfil")
        ]
        cat.add_option(CleanerOption(
            opt_id=f"{cat_id}__{fn}__web_cache",
            label=f"⚡ Caché Web — [{dn}]",
            description=f"Elimina archivos temporales de páginas web, JS compilado e imágenes en {dn}.",
            actions=web_cache_actions,
            default_checked=True
        ))

        # 2.2 GPU & Shader Cache
        gpu_actions = [
            ActionDelete(os.path.join(cp, "GPUCache"), "walk.all", "GPUCache"),
            ActionDelete(os.path.join(cp, "DawnCache"), "walk.all", "DawnCache"),
            ActionDelete(os.path.join(cp, "ShaderCache"), "walk.all", "ShaderCache"),
            ActionDelete(os.path.join(cp, "GrShaderCache"), "walk.all", "GrShaderCache")
        ]
        cat.add_option(CleanerOption(
            opt_id=f"{cat_id}__{fn}__gpu_cache",
            label=f"🎮 GPU & Shader Cache — [{dn}]",
            description=f"Caché de aceleración gráfica y shaders WebGL en {dn}.",
            actions=gpu_actions,
            default_checked=True
        ))

        # 2.3 Service Worker Cache Storage
        sw_actions = [
            ActionDelete(os.path.join(cp, "Service Worker", "CacheStorage"), "walk.all", "Service Worker Cache"),
            ActionDelete(os.path.join(cp, "Service Worker", "ScriptCache"), "walk.all", "Service Worker ScriptCache")
        ]
        cat.add_option(CleanerOption(
            opt_id=f"{cat_id}__{fn}__service_workers",
            label=f"🛠️ Service Workers Storage — [{dn}]",
            description=f"Caché offline de aplicaciones web en {dn} (preservando bases de datos de extensiones).",
            actions=sw_actions,
            default_checked=True
        ))

        # 2.4 SQLite VACUUM (Optimización sin pérdida de datos)
        vacuum_actions = [
            ActionVacuum(os.path.join(cp, "History"), "VACUUM History"),
            ActionVacuum(os.path.join(cp, "Cookies"), "VACUUM Cookies"),
            ActionVacuum(os.path.join(cp, "Network", "Cookies"), "VACUUM Network Cookies"),
            ActionVacuum(os.path.join(cp, "Favicons"), "VACUUM Favicons"),
            ActionVacuum(os.path.join(cp, "Top Sites"), "VACUUM Top Sites"),
            ActionVacuum(os.path.join(cp, "Shortcuts"), "VACUUM Shortcuts")
        ]
        cat.add_option(CleanerOption(
            opt_id=f"{cat_id}__{fn}__sqlite_vacuum",
            label=f"🗄️ SQLite VACUUM (Desfragmentar) — [{dn}]",
            description=f"Desfragmenta bases de datos SQLite en {dn} para reducir tamaño y acelerar consultas sin borrar nada.",
            actions=vacuum_actions,
            default_checked=True
        ))

    return cat


def build_system_cleaner_category() -> CleanerCategory:
    """Construye las opciones de limpieza del Sistema Operativo Linux."""
    cat = CleanerCategory(
        cat_id="linux_system",
        label="🐧 Sistema Linux & Entorno de Usuario",
        icon="🐧",
        description="Limpieza de miniaturas, papeleras del sistema y de montajes /mnt/, y temporales seguros."
    )

    # 1. Miniaturas (Thumbnails)
    cat.add_option(CleanerOption(
        opt_id="system__thumbnails",
        label="🖼️ Caché de Miniaturas (Thumbnails)",
        description="Elimina miniaturas generadas por el administrador de archivos en ~/.cache/thumbnails/.",
        actions=[
            ActionDelete(os.path.expanduser("~/.cache/thumbnails"), "walk.all", "Thumbnails ~/.cache")
        ],
        default_checked=True
    ))

    # 2. Papelera de Reciclaje de Usuario
    cat.add_option(CleanerOption(
        opt_id="system__trash",
        label="🗑️ Papelera del Sistema (~/.local/share/Trash)",
        description="Vacía los archivos de la papelera en ~/.local/share/Trash/ (files, expunged, info).",
        actions=[
            ActionDelete(os.path.expanduser("~/.local/share/Trash/files"), "walk.all", "Papelera Files"),
            ActionDelete(os.path.expanduser("~/.local/share/Trash/info"), "walk.all", "Papelera Info"),
            ActionDelete(os.path.expanduser("~/.local/share/Trash/expunged"), "walk.all", "Papelera Expunged")
        ],
        default_checked=False,
        is_warning=True,
        warning_msg="Los archivos en la papelera del sistema serán eliminados permanentemente."
    ))

    # 3. Papeleras de Montajes en /mnt/
    cat.add_option(CleanerOption(
        opt_id="system__mnt_trash",
        label="💾 Papeleras en Montajes /mnt/ (.recycle, .Trash-*)",
        description="Busca y vacía carpetas .recycle y .Trash-* en puntos de montaje /mnt/ (discos externos y red) con timeout anti-cuelgues. Requiere Sudo para permisos de root.",
        actions=[
            ActionTrashMounts("Papeleras en /mnt/*")
        ],
        default_checked=False,
        is_warning=True,
        warning_msg="Elimina permanentemente papeleras en unidades montadas de /mnt/. Se recomienda activar Modo Sudo."
    ))

    # 4. Temporales Seguros de Usuario en /tmp
    cat.add_option(CleanerOption(
        opt_id="system__user_tmp",
        label="🧹 Archivos Temporales de Usuario (/tmp)",
        description="Elimina sockets efímeros y archivos temporales creados por el usuario en /tmp.",
        actions=[
            ActionDelete(f"/tmp/hsperfdata_{CURRENT_USER}", "walk.all", "Java TMP"),
            ActionDelete(f"/tmp/.org.chromium.Chromium.*", "glob", "Chromium TMP Sockets"),
            ActionDelete(f"/tmp/.org.chromium.*", "glob", "Chromium TMP Files")
        ],
        default_checked=True
    ))

    # 5. Logs Rotados y Crash Dumps de Usuario
    cat.add_option(CleanerOption(
        opt_id="system__user_logs",
        label="📋 Crash Dumps & Logs Efímeros",
        description="Elimina archivos de volcado de fallos y logs antiguos en ~/.local/share/xorg/ y caché.",
        actions=[
            ActionDelete(os.path.expanduser("~/.cache/fontconfig"), "walk.all", "Fontconfig cache"),
            ActionDelete(os.path.expanduser("~/.cache/mesa_shader_cache"), "walk.all", "Mesa Shader Cache"),
            ActionDelete(os.path.expanduser("~/.cache/gstreamer-1.0"), "walk.all", "Gstreamer cache")
        ],
        default_checked=True
    ))

    return cat


# ── 6. WORKER ASÍNCRONO MULTIHILO (CLEANER WORKER) ────────────────────────────
class CleanerWorker(CancellableThread):
    """
    Worker que ejecuta el escaneo (preview) o la limpieza real
    siguiendo la arquitectura y generadores de BleachBit.
    """
    sig_log = pyqtSignal(str, str)          # (mensaje, nivel: info, success, warning, error, header)
    sig_progress = pyqtSignal(int, int)     # (actual, total)
    sig_stats = pyqtSignal(int, int, int, int) # (bytes_freed, files_processed, errors, protected_count)
    sig_finished = pyqtSignal(dict)         # resumen final

    def __init__(self, selected_options: List[CleanerOption], really_delete: bool, use_sudo: bool = False, parent=None):
        super().__init__(parent)
        self.selected_options = selected_options
        self.really_delete = really_delete
        self.use_sudo = use_sudo
        self.total_bytes = 0
        self.total_files = 0
        self.total_errors = 0
        self.total_protected = 0

    def run(self):
        mode_str = "LIMPIEZA REAL" if self.really_delete else "VISTA PREVIA / DRY-RUN"
        sudo_tag = " [MODO SUDO]" if self.use_sudo else ""
        self.sig_log.emit(f"🚀 Iniciando {mode_str}{sudo_tag} con {len(self.selected_options)} opciones seleccionadas...", "header")
        start_time = time.time()

        # Contar total de acciones para la barra de progreso
        total_actions = sum(len(opt.actions) for opt in self.selected_options)
        current_action_idx = 0

        # Verificar si hay navegadores vivos antes de limpiar
        if self.really_delete:
            running_browsers = []
            for proc in psutil.process_iter(["name", "username"]):
                try:
                    if proc.info["username"] == CURRENT_USER:
                        pname = (proc.info["name"] or "").lower()
                        if "chrome" in pname or "brave" in pname:
                            running_browsers.append(pname)
                except Exception:
                    pass
            if running_browsers:
                unique_b = list(set(running_browsers))
                self.sig_log.emit(
                    f"⚠️ Advertencia: Detectados procesos activos de navegador ({', '.join(unique_b)}). "
                    "Los archivos bloqueados en uso serán omitidos de forma segura.", "warning"
                )

        for opt in self.selected_options:
            if self.is_cancelled():
                self.sig_log.emit("⏹️ Operación cancelada por el usuario.", "warning")
                break

            self.sig_log.emit(f"📂 Procesando: {opt.label}", "info")

            for action in opt.actions:
                if self.is_cancelled():
                    break

                current_action_idx += 1
                self.sig_progress.emit(current_action_idx, max(1, total_actions))

                try:
                    for bytes_freed, path, status in action.execute(self.really_delete, use_sudo=self.use_sudo):
                        if self.is_cancelled():
                            break

                        if status == "PROTECTED":
                            self.total_protected += 1
                        elif status in ("DELETED", "PREVIEW") or status.startswith("DELETED (sudo)"):
                            self.total_bytes += bytes_freed
                            self.total_files += 1
                            if "sudo" in status:
                                self.sig_log.emit(f"  🔑 [SUDO] Eliminado: {os.path.basename(path)} ({format_bytes(bytes_freed)})", "success")
                            if self.total_files % 50 == 0:
                                self.sig_stats.emit(self.total_bytes, self.total_files, self.total_errors, self.total_protected)
                        elif status == "VACUUMED":
                            self.total_bytes += bytes_freed
                            self.total_files += 1
                            self.sig_log.emit(f"  ✨ [VACUUM] Base de datos compactada: {os.path.basename(path)} (Liberados: {format_bytes(bytes_freed)})", "success")
                        elif status.startswith("ERROR"):
                            self.total_errors += 1
                            self.sig_log.emit(f"  ❌ Error en {os.path.basename(path)}: {status}", "error")
                        elif status.startswith("PERMISSION_DENIED"):
                            self.total_errors += 1
                            self.sig_log.emit(f"  🔒 Permiso denegado en {path}. {status}", "warning")

                except Exception as exc:
                    self.total_errors += 1
                    self.sig_log.emit(f"  ❌ Excepción en acción: {exc}", "error")

            self.sig_stats.emit(self.total_bytes, self.total_files, self.total_errors, self.total_protected)

        duration_ms = int((time.time() - start_time) * 1000)
        summary = {
            "mode": "real" if self.really_delete else "preview",
            "total_bytes": self.total_bytes,
            "total_files": self.total_files,
            "total_errors": self.total_errors,
            "total_protected": self.total_protected,
            "duration_ms": duration_ms,
            "cancelled": self.is_cancelled()
        }

        # Registrar en Action Journal SRE
        log_sre_action(
            action="bleachbit_clean" if self.really_delete else "bleachbit_preview",
            target=f"{len(self.selected_options)} opciones",
            result="COMPLETED" if not self.is_cancelled() else "CANCELLED",
            duration_ms=duration_ms,
            detail=f"Liberados: {format_bytes(self.total_bytes)}, Archivos: {self.total_files}, Errores: {self.total_errors}, Protegidos: {self.total_protected}"
        )

        final_msg = (
            f"✅ {mode_str} COMPLETADA en {duration_ms / 1000:.2f}s | "
            f"Espacio: {format_bytes(self.total_bytes)} | "
            f"Archivos: {self.total_files} | "
            f"Bóvedas/Extensiones Protegidas: {self.total_protected}"
        )
        self.sig_log.emit(final_msg, "header")
        self.sig_finished.emit(summary)


# ── 7. WIDGET PRINCIPAL DE LA PESTAÑA (TAB CLEANER) ───────────────────────────
class TabCleaner(QWidget):
    """
    Pestaña 7 de FloydIA Suite: Motor de Limpieza BleachBit con soporte Multi-Perfil
    y Protección de Bóvedas de Bitwarden.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.categories: List[CleanerCategory] = []
        self.worker: Optional[CleanerWorker] = None
        self.script_worker: Optional[ScriptRunnerWorker] = None
        self.init_categories()
        self.init_ui()

    def init_categories(self):
        """Inicializa los limpiadores descubriendo perfiles de Chrome, Brave y Sistema."""
        self.categories.clear()

        # 1. Google Chrome Multi-Perfil
        chrome_cat = build_chromium_cleaner_category(
            cat_id="google_chrome",
            browser_label="Google Chrome",
            browser_icon="🌐",
            config_base="~/.config/google-chrome",
            cache_base="~/.cache/google-chrome"
        )
        if chrome_cat:
            self.categories.append(chrome_cat)

        # 2. Brave Browser Multi-Perfil
        brave_cat = build_chromium_cleaner_category(
            cat_id="brave_browser",
            browser_label="Brave Browser",
            browser_icon="🦁",
            config_base="~/.config/BraveSoftware/Brave-Browser",
            cache_base="~/.cache/BraveSoftware/Brave-Browser"
        )
        if brave_cat:
            self.categories.append(brave_cat)

        # 3. Sistema Operativo Linux
        sys_cat = build_system_cleaner_category()
        self.categories.append(sys_cat)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── CABECERA SUPERIOR & SHIELD DE PROTECCIÓN ──────────────────────────
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background-color: {COLOR_BG_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 12px;")
        header_lay = QHBoxLayout(header_frame)
        header_lay.setContentsMargins(12, 8, 12, 8)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        lbl_title = QLabel("🧹 SRE BleachBit Cleaner & Multi-Profile Optimizer")
        lbl_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        lbl_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")

        lbl_desc = QLabel("Motor de limpieza profunda modular. Soporta todos los perfiles independientes de Google Chrome y Brave.")
        lbl_desc.setFont(QFont("Inter", 8))
        lbl_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_desc)
        header_lay.addLayout(title_box)
        header_lay.addStretch()

        # Shield Badge Inmutable
        shield_badge = QFrame()
        shield_badge.setStyleSheet("background-color: rgba(16, 185, 129, 0.15); border: 1px solid #10B981; border-radius: 6px; padding: 6px 12px;")
        shield_lay = QHBoxLayout(shield_badge)
        shield_lay.setContentsMargins(6, 4, 6, 4)
        lbl_shield = QLabel("🛡️ Bitwarden & Extensiones: Allowlist Activa")
        lbl_shield.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        lbl_shield.setStyleSheet("color: #10B981;")
        shield_lay.addWidget(lbl_shield)
        header_lay.addWidget(shield_badge)

        layout.addWidget(header_frame)

        # ── KPI METRICS CARDS ─────────────────────────────────────────────────
        kpi_lay = QHBoxLayout()
        kpi_lay.setSpacing(10)

        self.kpi_space = self._create_kpi_card("📦 Espacio Liberable", "0.00 MB", COLOR_PRIMARY_CYAN)
        self.kpi_files = self._create_kpi_card("📄 Archivos Analizados", "0", COLOR_SECONDARY_BLUE)
        self.kpi_protected = self._create_kpi_card("🛡️ Bóvedas Blindadas", "100% Seguras", COLOR_SUCCESS)
        self.kpi_errors = self._create_kpi_card("⚠️ Omitidos / Bloqueados", "0", COLOR_WARNING)

        kpi_lay.addWidget(self.kpi_space)
        kpi_lay.addWidget(self.kpi_files)
        kpi_lay.addWidget(self.kpi_protected)
        kpi_lay.addWidget(self.kpi_errors)
        layout.addLayout(kpi_lay)

        # ── SPLITTER PRINCIPAL: ÁRBOL BLEACHBIT + CONSOLA ─────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #1E3A5F; width: 2px; }")

        # PANEL IZQUIERDO: Árbol de Opciones
        left_widget = QWidget()
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 8, 0)
        left_lay.setSpacing(8)

        # Barra de búsqueda y presets rápidos
        preset_lay = QHBoxLayout()
        self.btn_select_all = QPushButton("✅ Todo")
        self.btn_select_all.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.btn_select_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_all.clicked.connect(lambda: self.set_all_checked(True))

        self.btn_select_safe = QPushButton("🛡️ Solo Cachés")
        self.btn_select_safe.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.btn_select_safe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_safe.clicked.connect(self.select_safe_presets)

        self.btn_select_none = QPushButton("❌ Deseleccionar")
        self.btn_select_none.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.btn_select_none.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select_none.clicked.connect(lambda: self.set_all_checked(False))

        preset_lay.addWidget(self.btn_select_all)
        preset_lay.addWidget(self.btn_select_safe)
        preset_lay.addWidget(self.btn_select_none)
        left_lay.addLayout(preset_lay)

        # QTreeWidget con checkboxes al estilo BleachBit
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 6px;
                color: {COLOR_TEXT_MAIN};
            }}
            QTreeWidget::item {{
                padding: 4px;
                border-radius: 4px;
            }}
            QTreeWidget::item:hover {{
                background-color: rgba(0, 245, 212, 0.08);
            }}
            QTreeWidget::item:selected {{
                background-color: rgba(0, 245, 212, 0.15);
                color: {COLOR_PRIMARY_CYAN};
            }}
        """)
        self.tree.itemChanged.connect(self.on_tree_item_changed)
        self.tree.itemClicked.connect(self.on_tree_item_clicked)
        self.populate_tree()
        left_lay.addWidget(self.tree)

        # Tarjeta de Descripción Contextual
        self.desc_card = QFrame()
        self.desc_card.setStyleSheet(f"background-color: {COLOR_BG_DARK}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 8px;")
        desc_lay = QVBoxLayout(self.desc_card)
        desc_lay.setContentsMargins(6, 6, 6, 6)
        desc_lay.setSpacing(4)
        self.lbl_opt_title = QLabel("Detalle de la Opción")
        self.lbl_opt_title.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.lbl_opt_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        self.lbl_opt_detail = QLabel("Selecciona cualquier elemento del árbol para consultar su alcance.")
        self.lbl_opt_detail.setFont(QFont("Inter", 8))
        self.lbl_opt_detail.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        self.lbl_opt_detail.setWordWrap(True)
        desc_lay.addWidget(self.lbl_opt_title)
        desc_lay.addWidget(self.lbl_opt_detail)
        left_lay.addWidget(self.desc_card)

        splitter.addWidget(left_widget)

        # PANEL DERECHO: Consola de Salida & Barra de Progreso
        right_widget = QWidget()
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(8, 0, 0, 0)
        right_lay.setSpacing(8)

        # Consola de Registro en Tiempo Real
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("JetBrains Mono, Fira Code, monospace", 8))
        self.console.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {COLOR_BG_DARK};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 8px;
                color: #A8B3C2;
            }}
        """)
        right_lay.addWidget(self.console)

        # Barra de Progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLOR_BG_DARK};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00BBF9, stop:1 {COLOR_PRIMARY_CYAN});
                border-radius: 3px;
            }}
        """)
        right_lay.addWidget(self.progress_bar)

        # Barra de Sudo y Acciones Rápidas
        sudo_bar = QHBoxLayout()
        sudo_bar.setSpacing(10)

        self.chk_sudo = QCheckBox("🔑 Modo Privilegiado (sudo)")
        self.chk_sudo.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.chk_sudo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_sudo.setToolTip("Habilita permisos de root para eliminar papeleras en /mnt/ y archivos del sistema protegidos.")
        self.chk_sudo.setStyleSheet(f"""
            QCheckBox {{
                color: {COLOR_TEXT_MAIN};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {COLOR_PRIMARY_CYAN};
                border-radius: 4px;
                background-color: {COLOR_BG_DARK};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLOR_PRIMARY_CYAN};
            }}
        """)
        self.chk_sudo.toggled.connect(self.on_sudo_toggled)

        self.lbl_sudo_status = QLabel("🛡️ Sudo: Inactivo")
        self.lbl_sudo_status.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.lbl_sudo_status.setStyleSheet("color: #94A3B8; background-color: rgba(148, 163, 184, 0.1); border: 1px solid #475569; border-radius: 4px; padding: 3px 8px;")

        self.btn_run_script = QPushButton("⚡ Limpiar Papeleras (Script)")
        self.btn_run_script.setFixedHeight(32)
        self.btn_run_script.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.btn_run_script.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_script.setToolTip("Ejecuta directamente SCRIPTS/limpiar_papeleras.sh reportando en tiempo real.")
        self.btn_run_script.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(0, 245, 212, 0.1);
                border: 1px solid {COLOR_PRIMARY_CYAN};
                color: {COLOR_PRIMARY_CYAN};
                border-radius: 5px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 245, 212, 0.25);
            }}
        """)
        self.btn_run_script.clicked.connect(self.run_trash_script_directly)

        sudo_bar.addWidget(self.chk_sudo)
        sudo_bar.addWidget(self.lbl_sudo_status)
        sudo_bar.addStretch()
        sudo_bar.addWidget(self.btn_run_script)
        right_lay.addLayout(sudo_bar)

        # Botonera de Control Inferior
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_preview = QPushButton("🔍 1. Vista Previa / Analizar (Dry-Run)")
        self.btn_preview.setFixedHeight(42)
        self.btn_preview.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.btn_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preview.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_BG_CARD};
                border: 1px solid {COLOR_PRIMARY_CYAN};
                color: {COLOR_PRIMARY_CYAN};
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 245, 212, 0.15);
            }}
        """)
        self.btn_preview.clicked.connect(self.run_preview)

        self.btn_clean = QPushButton("🧹 2. Ejecutar Limpieza Real")
        self.btn_clean.setFixedHeight(42)
        self.btn_clean.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.btn_clean.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clean.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00F5D4, stop:1 #00BBF9);
                border: none;
                color: #050911;
                border-radius: 6px;
                padding: 0 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #20FFE0, stop:1 #38BDF8);
            }}
        """)
        self.btn_clean.clicked.connect(self.run_clean)

        self.btn_cancel = QPushButton("⏹️ Cancelar")
        self.btn_cancel.setFixedHeight(42)
        self.btn_cancel.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(239, 68, 68, 0.15);
                border: 1px solid {COLOR_DANGER};
                color: {COLOR_DANGER};
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: rgba(239, 68, 68, 0.3);
            }}
            QPushButton:disabled {{
                background-color: #101C30;
                border-color: #1E3A5F;
                color: #475569;
            }}
        """)
        self.btn_cancel.clicked.connect(self.cancel_operation)

        btn_bar.addWidget(self.btn_preview)
        btn_bar.addWidget(self.btn_clean)
        btn_bar.addWidget(self.btn_cancel)
        right_lay.addLayout(btn_bar)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        layout.addWidget(splitter)

        # Detectar sudo inicial
        if check_sudo_active():
            self.chk_sudo.setChecked(True)
            self.lbl_sudo_status.setText("🟢 Sudo: Activo (root)")
            self.lbl_sudo_status.setStyleSheet("color: #10B981; background-color: rgba(16, 185, 129, 0.15); border: 1px solid #10B981; border-radius: 4px; padding: 3px 8px;")

        # Log inicial de bienvenida
        self.append_log("🟢 Módulo SRE BleachBit Cleaner inicializado.", "success")
        self.append_log(f"🛡️ Allowlist de Bitwarden ({BITWARDEN_EXTENSION_ID}) y extensiones cargada.", "info")
        self.append_log(f"🔍 Detectadas {len(self.categories)} categorías de limpieza listas para analizar.", "info")

    def _create_kpi_card(self, title: str, val: str, color_hex: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"background-color: {COLOR_BG_CARD}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 8px;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Inter", 8))
        lbl_t.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        lbl_v = QLabel(val)
        lbl_v.setObjectName("ValLabel")
        lbl_v.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        lbl_v.setStyleSheet(f"color: {color_hex};")

        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)
        return card

    def _update_kpi(self, card: QFrame, val: str):
        lbl = card.findChild(QLabel, "ValLabel")
        if lbl:
            lbl.setText(val)

    # ── POBLADO Y GESTIÓN DEL ÁRBOL ───────────────────────────────────────────
    def populate_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()

        for cat in self.categories:
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, f"{cat.icon} {cat.label}")
            cat_item.setFont(0, QFont("Inter", 9, QFont.Weight.Bold))
            cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
            cat_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "category", "data": cat})

            for opt in cat.options:
                opt_item = QTreeWidgetItem(cat_item)
                opt_item.setText(0, opt.label)
                opt_item.setFont(0, QFont("Inter", 8))
                opt_item.setFlags(opt_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                opt_item.setCheckState(0, Qt.CheckState.Checked if opt.default_checked else Qt.CheckState.Unchecked)
                opt_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "option", "data": opt})

            cat_item.setExpanded(True)

        self.tree.blockSignals(False)

    def set_all_checked(self, checked: bool):
        self.tree.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setCheckState(0, state)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, state)
        self.tree.blockSignals(False)

    def select_safe_presets(self):
        """Selecciona únicamente cachés y deselecciona papelera y temporales críticos."""
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data.get("type") == "option":
                    opt: CleanerOption = data["data"]
                    if not opt.is_warning:
                        child.setCheckState(0, Qt.CheckState.Checked)
                    else:
                        child.setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)

    def on_tree_item_changed(self, item: QTreeWidgetItem, column: int):
        pass

    def on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        if data.get("type") == "option":
            opt: CleanerOption = data["data"]
            self.lbl_opt_title.setText(f"📌 {opt.label}")
            warn_str = f"\n⚠️ ADVERTENCIA: {opt.warning_msg}" if opt.is_warning else ""
            self.lbl_opt_detail.setText(f"{opt.description}{warn_str}\nAcciones programadas: {len(opt.actions)}")
        elif data.get("type") == "category":
            cat: CleanerCategory = data["data"]
            self.lbl_opt_title.setText(f"{cat.icon} {cat.label}")
            self.lbl_opt_detail.setText(f"{cat.description}\nOpciones disponibles: {len(cat.options)}")

    def get_selected_options(self) -> List[CleanerOption]:
        selected = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    data = child.data(0, Qt.ItemDataRole.UserRole)
                    if data and data.get("type") == "option":
                        selected.append(data["data"])
        return selected

    # ── LOGGING Y CONSOLA ─────────────────────────────────────────────────────
    def append_log(self, text: str, level: str = "info"):
        color_map = {
            "header": COLOR_PRIMARY_CYAN,
            "info": "#A8B3C2",
            "success": "#10B981",
            "warning": "#F59E0B",
            "error": "#EF4444"
        }
        color = color_map.get(level, "#A8B3C2")
        timestamp = time.strftime("%H:%M:%S")
        html = f"<span style='color: #475569;'>[{timestamp}]</span> <span style='color: {color};'>{text}</span>"
        self.console.appendHtml(html)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    # ── GESTIÓN DE SUDO Y EJECUCIÓN DIRECTA DE SCRIPTS ───────────────────────
    def on_sudo_toggled(self, checked: bool):
        if checked:
            # Comprobar si ya existe sesión de sudo activa o sin contraseña
            if check_sudo_active():
                self.lbl_sudo_status.setText("🟢 Sudo: Activo (root)")
                self.lbl_sudo_status.setStyleSheet("color: #10B981; background-color: rgba(16, 185, 129, 0.15); border: 1px solid #10B981; border-radius: 4px; padding: 3px 8px;")
                self.append_log("🔑 Modo Sudo activado con éxito (privilegios de root verificados).", "success")
                return

            # Si requiere contraseña, solicitarla mediante diálogo modal seguro
            pwd, ok = QInputDialog.getText(
                self,
                "Autenticación Sudo",
                "Introduce la contraseña de sudo para habilitar permisos de root:",
                QLineEdit.EchoMode.Password
            )
            if ok and pwd:
                try:
                    p = subprocess.run(["sudo", "-S", "-v"], input=(pwd + "\n").encode(), capture_output=True, check=False)
                    if p.returncode == 0:
                        self.lbl_sudo_status.setText("🟢 Sudo: Activo (root)")
                        self.lbl_sudo_status.setStyleSheet("color: #10B981; background-color: rgba(16, 185, 129, 0.15); border: 1px solid #10B981; border-radius: 4px; padding: 3px 8px;")
                        self.append_log("🔑 Modo Sudo autenticado con éxito vía sudo -v.", "success")
                    else:
                        QMessageBox.warning(self, "Error Sudo", "Contraseña incorrecta. No se pudo habilitar Sudo.")
                        self._reset_sudo_ui()
                except Exception as e:
                    QMessageBox.warning(self, "Error Sudo", f"Fallo al autenticar: {e}")
                    self._reset_sudo_ui()
            else:
                self._reset_sudo_ui()
        else:
            self.lbl_sudo_status.setText("🛡️ Sudo: Inactivo")
            self.lbl_sudo_status.setStyleSheet("color: #94A3B8; background-color: rgba(148, 163, 184, 0.1); border: 1px solid #475569; border-radius: 4px; padding: 3px 8px;")
            self.append_log("🛡️ Modo Sudo desactivado.", "info")

    def _reset_sudo_ui(self):
        self.chk_sudo.blockSignals(True)
        self.chk_sudo.setChecked(False)
        self.chk_sudo.blockSignals(False)
        self.lbl_sudo_status.setText("🛡️ Sudo: Inactivo")
        self.lbl_sudo_status.setStyleSheet("color: #94A3B8; background-color: rgba(148, 163, 184, 0.1); border: 1px solid #475569; border-radius: 4px; padding: 3px 8px;")

    def run_trash_script_directly(self):
        """Ejecuta el script de limpieza de papeleras en streaming hacia la consola."""
        script_file = os.path.join(WORKSPACE_ROOT, "SCRIPTS", "limpiar_papeleras.sh")
        if not os.path.exists(script_file):
            script_file = "/home/tec/Dropbox/ANTIGRAVITY_PROJECTS/SCRIPTS/limpiar_papeleras.sh"

        if not os.path.exists(script_file):
            QMessageBox.critical(self, "Archivo no encontrado", f"No se encontró el script en: {script_file}")
            return

        use_sudo = self.chk_sudo.isChecked()
        if not use_sudo:
            reply = QMessageBox.question(
                self,
                "Ejecutar Script de Papeleras",
                "¿Deseas ejecutar el script de limpieza de papeleras?\n\n"
                "💡 Nota: El Modo Sudo está inactivo. Las papeleras de /mnt/ que requieran permisos de root podrían omitirse si no se activa Sudo.\n\n"
                "¿Deseas continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Ocupado", "Hay una tarea de limpieza en ejecución. Espera a que termine.")
            return

        if self.script_worker and self.script_worker.isRunning():
            return

        self.btn_preview.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.btn_run_script.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)

        sudo_txt = " (con privilegios Sudo)" if use_sudo else ""
        self.append_log(f"🚀 Ejecutando SCRIPTS/limpiar_papeleras.sh{sudo_txt}...", "header")

        self.script_worker = ScriptRunnerWorker(script_file, use_sudo=use_sudo, parent=self)
        self.script_worker.sig_line.connect(self.append_log)
        self.script_worker.sig_finished.connect(self.on_script_worker_finished)
        self.script_worker.start()

    def on_script_worker_finished(self, success: bool, msg: str):
        self.btn_preview.setEnabled(True)
        self.btn_clean.setEnabled(True)
        self.btn_run_script.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100)

    # ── ACCIONES DE EJECUCIÓN (PREVIEW / CLEAN) ───────────────────────────────
    def run_preview(self):
        self._start_worker(really_delete=False)

    def run_clean(self):
        selected = self.get_selected_options()
        if not selected:
            QMessageBox.information(self, "Sin Selección", "Por favor selecciona al menos una opción para limpiar.")
            return

        sudo_note = "\n🔑 Modo Sudo: ACTIVO (Operaciones privilegiadas permitidas)." if self.chk_sudo.isChecked() else "\n🛡️ Modo Sudo: INACTIVO (Solo permisos de usuario normal)."

        # Confirmación de Seguridad
        reply = QMessageBox.question(
            self,
            "Confirmar Limpieza",
            f"¿Deseas proceder con la limpieza real de {len(selected)} opciones seleccionadas?{sudo_note}\n\n"
            "🛡️ Las extensiones y las credenciales de Bitwarden están protegidas y no serán modificadas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_worker(really_delete=True)

    def _start_worker(self, really_delete: bool):
        selected = self.get_selected_options()
        if not selected:
            QMessageBox.information(self, "Sin Selección", "Por favor selecciona al menos una opción en el árbol.")
            return

        if self.worker and self.worker.isRunning():
            return

        use_sudo = self.chk_sudo.isChecked()

        self.btn_preview.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.btn_run_script.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)

        # Reset KPIs
        self._update_kpi(self.kpi_space, "Calculando...")
        self._update_kpi(self.kpi_files, "0")
        self._update_kpi(self.kpi_errors, "0")

        self.worker = CleanerWorker(selected, really_delete, use_sudo=use_sudo, parent=self)
        self.worker.sig_log.connect(self.append_log)
        self.worker.sig_progress.connect(self.on_worker_progress)
        self.worker.sig_stats.connect(self.on_worker_stats)
        self.worker.sig_finished.connect(self.on_worker_finished)
        self.worker.start()

    def cancel_operation(self):
        if self.worker and self.worker.isRunning():
            self.append_log("⏳ Solicitando cancelación ordenada del worker...", "warning")
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)
        if self.script_worker and self.script_worker.isRunning():
            self.append_log("⏳ Solicitando cancelación del script...", "warning")
            self.script_worker.cancel()
            self.btn_cancel.setEnabled(False)

    def on_worker_progress(self, current: int, total: int):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(pct)

    def on_worker_stats(self, total_bytes: int, files: int, errors: int, protected_count: int):
        self._update_kpi(self.kpi_space, format_bytes(total_bytes))
        self._update_kpi(self.kpi_files, f"{files:,}")
        self._update_kpi(self.kpi_errors, str(errors))
        self._update_kpi(self.kpi_protected, f"{protected_count} Bóvedas OK")

    def on_worker_finished(self, summary: dict):
        self.btn_preview.setEnabled(True)
        self.btn_clean.setEnabled(True)
        self.btn_run_script.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100)

        self._update_kpi(self.kpi_space, format_bytes(summary["total_bytes"]))
        self._update_kpi(self.kpi_files, f"{summary['total_files']:,}")
        self._update_kpi(self.kpi_errors, str(summary["total_errors"]))
        self._update_kpi(self.kpi_protected, f"{summary['total_protected']} Bóvedas OK")

    # ── PERSISTENCIA DE SESIÓN & SHUTDOWN ─────────────────────────────────────
    def save_state(self) -> dict:
        """Guarda los IDs de opciones que quedaron seleccionadas y el estado de sudo."""
        checked_ids = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    data = child.data(0, Qt.ItemDataRole.UserRole)
                    if data and data.get("type") == "option":
                        checked_ids.append(data["data"].opt_id)
        return {
            "checked_options": checked_ids,
            "sudo_enabled": self.chk_sudo.isChecked()
        }

    def restore_state(self, state: dict) -> None:
        """Restaura los checkboxes de sesión y el estado de sudo."""
        checked_ids = set(state.get("checked_options", []))
        if checked_ids:
            self.tree.blockSignals(True)
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                for j in range(top.childCount()):
                    child = top.child(j)
                    data = child.data(0, Qt.ItemDataRole.UserRole)
                    if data and data.get("type") == "option":
                        opt: CleanerOption = data["data"]
                        if opt.opt_id in checked_ids:
                            child.setCheckState(0, Qt.CheckState.Checked)
                        else:
                            child.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.blockSignals(False)

        if state.get("sudo_enabled", False):
            if check_sudo_active():
                self.chk_sudo.setChecked(True)

    def shutdown(self):
        """Detiene ordenadamente los workers si están en ejecución."""
        if self.worker and self.worker.isRunning():
            stop_worker(self.worker)
            self.worker = None
        if self.script_worker and self.script_worker.isRunning():
            stop_worker(self.script_worker)
            self.script_worker = None
