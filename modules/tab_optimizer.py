#!/usr/bin/env python3
"""
FLOYDIA SUITE 2.0 — Pestaña 2: Optimizador SRE, Limpieza de Memoria & Gestor de Procesos
Refactorizado con descubrimiento e inspección granular vía psutil, allowlists estrictas,
Action Journal estructurado y ciclo de vida determinista sin terminate() forzado.
"""

import os
import sys
import time
import json
import shutil
import subprocess
import signal
import getpass
from typing import Dict, Any, List, Optional, Tuple

import psutil
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer, QThread, QObject
from PyQt6.QtGui import QFont, QColor, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QProgressBar, QPlainTextEdit, QGridLayout,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QSplitter, QAbstractItemView
)

from theme import (
    COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BORDER, COLOR_PRIMARY_CYAN,
    COLOR_SECONDARY_BLUE, COLOR_SUCCESS, COLOR_DANGER, COLOR_WARNING,
    COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, CancellableThread, stop_worker, is_worker_running
)

CURRENT_USER = getpass.getuser()

def find_workspace_root() -> str:
    curr = os.path.abspath(__file__)
    while curr and curr != "/":
        if os.path.exists(os.path.join(curr, ".env")) or os.path.exists(os.path.join(curr, "requirements.txt")):
            return curr
        curr = os.path.dirname(curr)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKSPACE_ROOT = os.environ.get("FLOYDIA_WORKSPACE", find_workspace_root())
CACHE_DIR = os.path.join(WORKSPACE_ROOT, "cache")
ACTION_JOURNAL_FILE = os.path.join(CACHE_DIR, "action_journal.jsonl")


def log_sre_action(action: str, target: Any, result: str, duration_ms: int = 0, detail: str = "") -> None:
    """Registra una acción SRE estructurada en el Action Journal para auditoría."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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


def find_allowed_processes(tokens: List[str], username: Optional[str] = CURRENT_USER) -> List[psutil.Process]:
    """Descubre procesos vivos que coinciden con una allowlist de tokens específicos para el usuario."""
    wanted = tuple(t.lower() for t in tokens if t)
    found: List[psutil.Process] = []

    for proc in psutil.process_iter(["pid", "username", "exe", "cmdline"]):
        try:
            info = proc.info
            if username and info.get("username") != username:
                continue

            exe = (info.get("exe") or "").lower()
            cmdline = " ".join(info.get("cmdline") or []).lower()

            if any(token in exe or token in cmdline for token in wanted):
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return found


def terminate_verified_processes(processes: List[psutil.Process], grace_seconds: float = 1.5) -> Tuple[int, List[str]]:
    """Termina de forma cooperativa con SIGTERM y gracia de espera antes de SIGKILL."""
    terminated = 0
    errors: List[str] = []

    for proc in processes:
        try:
            if proc.pid in {os.getpid(), os.getppid()}:
                continue
            proc.terminate()
            terminated += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            errors.append(f"PID {proc.pid}: {exc}")

    _, alive = psutil.wait_procs(processes, timeout=grace_seconds)

    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            errors.append(f"PID {proc.pid}: {exc}")

    return terminated, errors


def find_listener(port: int) -> List[psutil.Process]:
    """Descubre los procesos que tienen abierto un socket TCP en estado LISTEN en el puerto dado."""
    listeners: List[psutil.Process] = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            try:
                if not conn.laddr or conn.laddr.port != port:
                    continue
                if conn.status != psutil.CONN_LISTEN or conn.pid is None:
                    continue
                listeners.append(psutil.Process(conn.pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.AccessDenied, Exception):
        pass
    return listeners


class MemoryReader:
    @staticmethod
    def get_stats() -> dict:
        """Obtiene métricas de RAM y Swap usando psutil de forma ligera."""
        data = {
            "ram_total_mb": 0,
            "ram_used_mb": 0,
            "ram_free_mb": 0,
            "ram_pct": 0,
            "swap_total_mb": 0,
            "swap_used_mb": 0,
            "swap_pct": 0
        }
        try:
            vmem = psutil.virtual_memory()
            smem = psutil.swap_memory()

            data["ram_total_mb"] = vmem.total // (1024 * 1024)
            data["ram_used_mb"] = vmem.used // (1024 * 1024)
            data["ram_free_mb"] = vmem.available // (1024 * 1024)
            data["ram_pct"] = int(vmem.percent)

            data["swap_total_mb"] = smem.total // (1024 * 1024)
            data["swap_used_mb"] = smem.used // (1024 * 1024)
            data["swap_pct"] = int(smem.percent)
        except Exception:
            # Fallback a /proc/meminfo
            try:
                with open("/proc/meminfo", "r") as f:
                    lines = f.readlines()
                mem = {}
                for line in lines:
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem[parts[0].strip()] = int(parts[1].strip().split()[0])

                total = mem.get("MemTotal", 1)
                free = mem.get("MemFree", 0)
                avail = mem.get("MemAvailable", free)
                used = total - avail

                data["ram_total_mb"] = total // 1024
                data["ram_used_mb"] = used // 1024
                data["ram_free_mb"] = avail // 1024
                data["ram_pct"] = int((used / total) * 100) if total > 0 else 0

                swap_total = mem.get("SwapTotal", 0)
                swap_free = mem.get("SwapFree", 0)
                swap_used = swap_total - swap_free
                data["swap_total_mb"] = swap_total // 1024
                data["swap_used_mb"] = swap_used // 1024
                data["swap_pct"] = int((swap_used / swap_total) * 100) if swap_total > 0 else 0
            except Exception:
                pass
        return data


class OptimizerWorker(CancellableThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, tasks: List[str]):
        super().__init__()
        self.tasks = tasks

    def run(self):
        total_tasks = len(self.tasks)
        if total_tasks == 0:
            self.finished_signal.emit(True, "Sin tareas seleccionadas.")
            return

        self.log_signal.emit("⚡ Iniciando ciclo de optimización SRE (Modo Seguro con psutil)...")
        step = 0
        t0 = time.time()

        for task in self.tasks:
            if self.is_cancelled():
                self.log_signal.emit("🛑 Optimización cancelada por el usuario.")
                self.finished_signal.emit(False, "Operación cancelada.")
                return

            step += 1
            pct = int((step / total_tasks) * 100)

            if task == "drop_caches":
                self.log_signal.emit("🧹 [1/5] Purgando PageCache, Dentries e Inodos (drop_caches)...")
                try:
                    subprocess.run(["sync"], check=False, timeout=5)
                    res = subprocess.run(
                        ["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
                        capture_output=True, text=True, timeout=4, check=False
                    )
                    if res.returncode == 0:
                        self.log_signal.emit("  ✅ Cachés de kernel purgadas con éxito (drop_caches 3).")
                        log_sre_action("drop_caches", "/proc/sys/vm/drop_caches", "success")
                    else:
                        self.log_signal.emit("  ℹ️ Sync ejecutado (elevación omitida o no requerida).")
                        log_sre_action("drop_caches", "sync_only", "notice", detail=res.stderr.strip())
                except subprocess.TimeoutExpired:
                    self.log_signal.emit("  ⚠️ drop_caches excedió el timeout de 4s.")
                    log_sre_action("drop_caches", "timeout", "warning")
                except Exception as e:
                    self.log_signal.emit(f"  ℹ️ Sync ejecutado: {e}")

            elif task == "orphan_mcps":
                self.log_signal.emit("🧟 [2/5] Buscando procesos huérfanos de MCP vía allowlist psutil...")
                try:
                    mcp_procs = find_allowed_processes(["mcp-server", "playwright-runner", "novamira-mcp", "inkscape_mcp", "notebooklm-mcp"])
                    if mcp_procs:
                        self.log_signal.emit(f"  🔍 Detectados {len(mcp_procs)} procesos MCP verificados. Saneando...")
                        term_count, errs = terminate_verified_processes(mcp_procs, grace_seconds=1.5)
                        self.log_signal.emit(f"  ✅ {term_count} procesos MCP terminados limpiamente con SIGTERM/SIGKILL.")
                        log_sre_action("orphan_mcps", [p.pid for p in mcp_procs], "success", detail=f"Terminated {term_count}")
                    else:
                        self.log_signal.emit("  ✅ No se detectaron procesos MCP zombies o huérfanos.")
                except Exception as e:
                    self.log_signal.emit(f"  ⚠️ Saneador MCP: {e}")
                    log_sre_action("orphan_mcps", "error", "failed", detail=str(e))

            elif task == "port_9333":
                self.log_signal.emit("🔌 [3/5] Verificando socket en puerto 9333 (AutoAccept listener)...")
                try:
                    listeners = find_listener(9333)
                    verified_targets = []
                    for proc in listeners:
                        try:
                            exe = (proc.exe() or "").lower()
                            cmdline = " ".join(proc.cmdline()).lower()
                            if "autoaccept" in exe or "autoaccept" in cmdline or proc.username() == CURRENT_USER:
                                verified_targets.append(proc)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    if verified_targets:
                        term_count, _ = terminate_verified_processes(verified_targets, grace_seconds=1.5)
                        self.log_signal.emit(f"  ✅ Listener del puerto 9333 liberado de forma segura ({term_count} PIDs).")
                        log_sre_action("port_9333", [p.pid for p in verified_targets], "success")
                    else:
                        self.log_signal.emit("  ✅ Puerto 9333 libre de listeners zombies.")
                except Exception as e:
                    self.log_signal.emit(f"  ℹ️ Puerto 9333 OK: {e}")

            elif task == "trash_clean":
                self.log_signal.emit("🗑️ [4/5] Vaciando Papelera (~/.local/share/Trash)...")
                trash_dir = os.path.expanduser("~/.local/share/Trash")
                if os.path.exists(trash_dir):
                    try:
                        count = 0
                        for root_dir, dirs, files in os.walk(trash_dir):
                            for f in files:
                                try:
                                    os.remove(os.path.join(root_dir, f))
                                    count += 1
                                except Exception:
                                    pass
                            for d in dirs:
                                try:
                                    shutil.rmtree(os.path.join(root_dir, d), ignore_errors=True)
                                except Exception:
                                    pass
                        self.log_signal.emit(f"  ✅ Papelera saneada ({count} elementos eliminados).")
                        log_sre_action("trash_clean", trash_dir, "success", detail=f"{count} files removed")
                    except Exception as e:
                        self.log_signal.emit(f"  ⚠️ Papelera: {e}")
                else:
                    self.log_signal.emit("  ✅ Papelera limpia.")

            elif task == "browser_mem":
                self.log_signal.emit("🌐 [5/5] Saneando manejadores crashpad de navegadores...")
                try:
                    crashpad_procs = find_allowed_processes(["crashpad-handler", "crashpad_handler"])
                    if crashpad_procs:
                        term_count, _ = terminate_verified_processes(crashpad_procs, grace_seconds=1.5)
                        self.log_signal.emit(f"  ✅ {term_count} procesos crashpad liberados.")
                        log_sre_action("browser_mem", [p.pid for p in crashpad_procs], "success")
                    else:
                        self.log_signal.emit("  ✅ Navegadores sin procesos residuales.")
                except Exception as e:
                    self.log_signal.emit(f"  ℹ️ Navegadores OK: {e}")

            self.progress_signal.emit(pct)
            time.sleep(0.08)

        duration = int((time.time() - t0) * 1000)
        log_sre_action("full_optimization_cycle", self.tasks, "completed", duration_ms=duration)
        self.finished_signal.emit(True, "¡Optimización SRE completada exitosamente!")


class ProcessScannerWorker(CancellableThread):
    processes_ready = pyqtSignal(list)

    def run(self):
        proc_list = []
        try:
            # Escaneo con psutil de alta eficiencia
            for proc in psutil.process_iter(["pid", "username", "cpu_percent", "memory_percent", "memory_info", "name", "cmdline"]):
                if self.is_cancelled():
                    return
                try:
                    info = proc.info
                    pid = str(info["pid"])
                    user = info["username"] or "unknown"
                    cpu = str(round(info.get("cpu_percent") or 0.0, 1))
                    mem_pct = str(round(info.get("memory_percent") or 0.0, 1))
                    rss_bytes = info["memory_info"].rss if info.get("memory_info") else 0
                    mb = round(rss_bytes / (1024 * 1024), 1)

                    cmdline = info.get("cmdline") or []
                    cmd_full = " ".join(cmdline) if cmdline else (info.get("name") or "")
                    cmd_short = info.get("name") or (os.path.basename(cmdline[0]) if cmdline else "proc")

                    proc_list.append({
                        "pid": pid,
                        "user": user,
                        "cpu": cpu,
                        "mem": mem_pct,
                        "mb": mb,
                        "cmd_short": cmd_short,
                        "cmd_full": cmd_full
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Ordenar por uso de MB descendente
            proc_list.sort(key=lambda x: x["mb"], reverse=True)
            # Top 45 procesos
            proc_list = proc_list[:45]
        except Exception:
            pass

        if not self.is_cancelled():
            self.processes_ready.emit(proc_list)


class ProcessActionWorker(CancellableThread):
    action_finished = pyqtSignal(str)

    def __init__(self, action_type: str, targets: List[str], extra: Optional[Dict] = None):
        super().__init__()
        self.action_type = action_type
        self.targets = targets
        self.extra = extra or {}

    def run(self):
        t0 = time.time()
        if self.action_type == "kill":
            killed = 0
            procs_to_terminate = []
            for pid_str in self.targets:
                if self.is_cancelled():
                    break
                try:
                    pid = int(pid_str)
                    proc = psutil.Process(pid)
                    procs_to_terminate.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            killed, _ = terminate_verified_processes(procs_to_terminate, grace_seconds=1.5)
            duration = int((time.time() - t0) * 1000)
            log_sre_action("kill_processes", self.targets, "completed", duration_ms=duration, detail=f"Terminated {killed}")
            self.action_finished.emit(f"💀 Se terminaron {killed} procesos de forma segura.")

        elif self.action_type == "restart_service":
            for pid in self.targets:
                if self.is_cancelled():
                    break
                name = self.extra.get(pid, "").lower()
                if "syncthing" in name:
                    subprocess.run(["systemctl", "--user", "restart", "syncthing.service"], capture_output=True, text=True, check=False)
                elif "networkmanager" in name:
                    subprocess.run(["sudo", "systemctl", "restart", "NetworkManager"], capture_output=True, text=True, check=False)
            log_sre_action("restart_service", self.targets, "completed")
            self.action_finished.emit("🔄 Servicios reiniciados.")


class TabOptimizer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_processes: List[Dict[str, Any]] = []
        self.table_checkboxes: Dict[str, QCheckBox] = {}
        self.opt_worker: Optional[OptimizerWorker] = None
        self.proc_worker: Optional[ProcessScannerWorker] = None
        self.action_worker: Optional[ProcessActionWorker] = None
        self.mem_timer: Optional[QTimer] = None
        self.proc_timer: Optional[QTimer] = None

        self.init_ui()
        self.start_monitors()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # 1. Encabezado
        top_box = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("⚡ Optimizador SRE, Limpieza de Memoria & Procesos")
        title.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        
        subtitle = QLabel("Monitoreo en vivo de RAM/Swap con psutil, saneamiento con allowlists y Action Journal")
        subtitle.setFont(QFont("Inter", 10))
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_box.addLayout(title_box)
        top_box.addStretch()

        self.btn_full_opt = QPushButton("🚀 OPTIMIZACIÓN TOTAL (1 CLIC)")
        self.btn_full_opt.setObjectName("PrimaryBtn")
        self.btn_full_opt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_full_opt.clicked.connect(self.run_all_optimizations)
        top_box.addWidget(self.btn_full_opt)

        layout.addLayout(top_box)

        # 2. Telemetría de Memoria en Vivo (RAM + Swap)
        mem_group = QFrame()
        mem_group.setProperty("class", "CardFrame")
        mem_lay = QVBoxLayout(mem_group)
        mem_lay.setContentsMargins(12, 10, 12, 10)
        mem_lay.setSpacing(8)

        mem_title = QLabel("📊 Telemetría de Recursos del Sistema en Tiempo Real (HP15)")
        mem_title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        mem_title.setStyleSheet(f"color: {COLOR_SECONDARY_BLUE};")
        mem_lay.addWidget(mem_title)

        grid_mem = QGridLayout()
        grid_mem.setSpacing(8)

        # RAM
        self.lbl_ram = QLabel("Memoria RAM: -- MB / -- MB (--%)")
        self.lbl_ram.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.bar_ram = QProgressBar()
        self.bar_ram.setValue(0)
        grid_mem.addWidget(self.lbl_ram, 0, 0)
        grid_mem.addWidget(self.bar_ram, 0, 1)

        # Swap / ZRAM
        self.lbl_swap = QLabel("ZRAM / Swap: -- MB / -- MB (--%)")
        self.lbl_swap.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.bar_swap = QProgressBar()
        self.bar_swap.setValue(0)
        grid_mem.addWidget(self.lbl_swap, 1, 0)
        grid_mem.addWidget(self.bar_swap, 1, 1)

        mem_lay.addLayout(grid_mem)
        layout.addWidget(mem_group)

        # 3. Splitter: Tareas Rápidas de Limpieza (Arriba) / Gestor de Procesos (Abajo)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Panel de Tareas Rápidas
        tasks_box = QFrame()
        tasks_box.setProperty("class", "CardFrame")
        tasks_lay = QVBoxLayout(tasks_box)
        tasks_lay.setContentsMargins(10, 10, 10, 10)
        tasks_lay.setSpacing(8)

        tasks_top = QHBoxLayout()
        lbl_t_title = QLabel("🧹 Tareas de Limpieza & Saneamiento SRE")
        lbl_t_title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        tasks_top.addWidget(lbl_t_title)
        tasks_top.addStretch()

        self.btn_exec_tasks = QPushButton("Ejecutar Tareas Marcadas")
        self.btn_exec_tasks.setObjectName("SecondaryBtn")
        self.btn_exec_tasks.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exec_tasks.clicked.connect(self.run_selected_tasks)
        tasks_top.addWidget(self.btn_exec_tasks)
        tasks_lay.addLayout(tasks_top)

        grid_checks = QGridLayout()
        self.chk_drop_caches = QCheckBox("Liberar Cachés del Kernel & Buffers (drop_caches 3)")
        self.chk_drop_caches.setChecked(True)
        self.chk_orphan_mcps = QCheckBox("Sanear Servidores MCP Huérfanos & Zombies")
        self.chk_orphan_mcps.setChecked(True)
        self.chk_port_9333 = QCheckBox("Liberar Puerto 9333 de AutoAccept")
        self.chk_port_9333.setChecked(True)
        self.chk_trash = QCheckBox("Vaciar Papelera (~/.local/share/Trash)")
        self.chk_trash.setChecked(True)
        self.chk_browser = QCheckBox("Liberar Memoria Residual de Navegadores")
        self.chk_browser.setChecked(True)

        grid_checks.addWidget(self.chk_drop_caches, 0, 0)
        grid_checks.addWidget(self.chk_orphan_mcps, 0, 1)
        grid_checks.addWidget(self.chk_port_9333, 1, 0)
        grid_checks.addWidget(self.chk_trash, 1, 1)
        grid_checks.addWidget(self.chk_browser, 2, 0)
        tasks_lay.addLayout(grid_checks)

        splitter.addWidget(tasks_box)

        # Panel de Gestor de Procesos Pesados (QTableWidget)
        proc_box = QFrame()
        proc_box.setProperty("class", "CardFrame")
        proc_lay = QVBoxLayout(proc_box)
        proc_lay.setContentsMargins(10, 10, 10, 10)
        proc_lay.setSpacing(8)

        proc_top = QHBoxLayout()
        lbl_p_title = QLabel("⚙️ Gestor Granular de Procesos Pesados (Top RAM/CPU)")
        lbl_p_title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        lbl_p_title.setStyleSheet(f"color: {COLOR_PRIMARY_CYAN};")
        proc_top.addWidget(lbl_p_title)
        proc_top.addStretch()

        lbl_filter = QLabel("Filtro:")
        lbl_filter.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        proc_top.addWidget(lbl_filter)

        self.combo_proc_filter = QComboBox()
        self.combo_proc_filter.addItems([
            "Todos los Procesos",
            "Navegadores (Chrome/Brave/Firefox)",
            "Python / Node",
            "Runtimes de IA (Ollama/PyTorch)",
            "MCP & Servers"
        ])
        self.combo_proc_filter.currentIndexChanged.connect(self.apply_proc_filter)
        proc_top.addWidget(self.combo_proc_filter)

        self.btn_refresh_procs = QPushButton("🔄 Actualizar")
        self.btn_refresh_procs.setObjectName("SecondaryBtn")
        self.btn_refresh_procs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_procs.clicked.connect(self.scan_processes)
        proc_top.addWidget(self.btn_refresh_procs)

        proc_lay.addLayout(proc_top)

        # Tabla interactiva
        self.table_procs = QTableWidget()
        self.table_procs.setColumnCount(7)
        self.table_procs.setHorizontalHeaderLabels([
            "Sel", "PID", "Nombre / Proceso", "% RAM", "MB Estimados", "% CPU", "Usuario"
        ])
        self.table_procs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_procs.setColumnWidth(0, 40)
        self.table_procs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_procs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table_procs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        proc_lay.addWidget(self.table_procs)

        # Acciones de Procesos
        proc_actions = QHBoxLayout()
        btn_sel_all_p = QPushButton("Seleccionar Todos")
        btn_sel_all_p.setObjectName("SecondaryBtn")
        btn_sel_all_p.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_sel_all_p.clicked.connect(lambda: self.toggle_all_proc_checks(True))
        
        btn_desel_all_p = QPushButton("Deseleccionar Todos")
        btn_desel_all_p.setObjectName("SecondaryBtn")
        btn_desel_all_p.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_desel_all_p.clicked.connect(lambda: self.toggle_all_proc_checks(False))

        proc_actions.addWidget(btn_sel_all_p)
        proc_actions.addWidget(btn_desel_all_p)
        proc_actions.addStretch()

        self.btn_restart_service = QPushButton("🔄 Reiniciar Servicio")
        self.btn_restart_service.setObjectName("SecondaryBtn")
        self.btn_restart_service.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_restart_service.clicked.connect(self.restart_selected_service)
        proc_actions.addWidget(self.btn_restart_service)

        self.btn_kill_procs = QPushButton("💀 Matar Procesos Seleccionados (SIGTERM / kill -9)")
        self.btn_kill_procs.setObjectName("DangerBtn")
        self.btn_kill_procs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_kill_procs.clicked.connect(self.kill_selected_processes)
        proc_actions.addWidget(self.btn_kill_procs)

        proc_lay.addLayout(proc_actions)
        splitter.addWidget(proc_box)
        splitter.setSizes([180, 320])

        layout.addWidget(splitter, stretch=1)

        # 4. Consola de Logs
        log_title = QLabel("📋 Bitácora de Optimización SRE & Action Journal")
        log_title.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        layout.addWidget(log_title)

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet(f"background-color: {COLOR_BG_DARK}; border: 1px solid {COLOR_BORDER}; font-family: monospace; font-size: 11px;")
        self.log_console.setMaximumHeight(100)
        self.log_console.setMaximumBlockCount(2000)
        layout.addWidget(self.log_console)

        self.log("✅ Optimizador SRE inicializado con psutil, Allowlists y Action Journal.")

    def log(self, text: str):
        self.log_console.appendPlainText(text)

    def start_monitors(self):
        self.update_memory_ui()
        self.scan_processes()

        self.mem_timer = QTimer(self)
        self.mem_timer.timeout.connect(self.update_memory_ui)
        self.mem_timer.start(3000)

        self.proc_timer = QTimer(self)
        self.proc_timer.timeout.connect(self.scan_processes)
        self.proc_timer.start(8000)

    def update_memory_ui(self):
        stats = MemoryReader.get_stats()
        
        # RAM
        r_pct = stats["ram_pct"]
        r_used = stats["ram_used_mb"]
        r_tot = stats["ram_total_mb"]
        self.lbl_ram.setText(f"Memoria RAM: {r_used} MB / {r_tot} MB ({r_pct}%)")
        self.bar_ram.setValue(r_pct)

        if r_pct < 60:
            self.bar_ram.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_SUCCESS}; }}")
        elif r_pct < 80:
            self.bar_ram.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_WARNING}; }}")
        else:
            self.bar_ram.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_DANGER}; }}")

        # Swap
        s_pct = stats["swap_pct"]
        s_used = stats["swap_used_mb"]
        s_tot = stats["swap_total_mb"]
        self.lbl_swap.setText(f"ZRAM / Swap: {s_used} MB / {s_tot} MB ({s_pct}%)")
        self.bar_swap.setValue(s_pct)

        if s_pct < 50:
            self.bar_swap.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_SUCCESS}; }}")
        else:
            self.bar_swap.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLOR_WARNING}; }}")

    def run_all_optimizations(self):
        tasks = ["drop_caches", "orphan_mcps", "port_9333", "trash_clean", "browser_mem"]
        self.start_optimization_worker(tasks)

    def run_selected_tasks(self):
        tasks = []
        if self.chk_drop_caches.isChecked(): tasks.append("drop_caches")
        if self.chk_orphan_mcps.isChecked(): tasks.append("orphan_mcps")
        if self.chk_port_9333.isChecked(): tasks.append("port_9333")
        if self.chk_trash.isChecked(): tasks.append("trash_clean")
        if self.chk_browser.isChecked(): tasks.append("browser_mem")

        if not tasks:
            QMessageBox.warning(self, "Sin Tareas", "Selecciona al menos una tarea de limpieza.")
            return

        self.start_optimization_worker(tasks)

    def start_optimization_worker(self, tasks: List[str]):
        if is_worker_running(self.opt_worker):
            return

        self.btn_full_opt.setEnabled(False)
        self.btn_exec_tasks.setEnabled(False)

        self.opt_worker = OptimizerWorker(tasks)
        self.opt_worker.log_signal.connect(self.log)
        self.opt_worker.finished_signal.connect(self.handle_optimization_finished)
        self.opt_worker.finished.connect(self._on_opt_worker_finished)
        self.opt_worker.start()

    def _on_opt_worker_finished(self):
        if self.opt_worker:
            self.opt_worker.deleteLater()
            self.opt_worker = None

    def handle_optimization_finished(self, success: bool, msg: str):
        self.btn_full_opt.setEnabled(True)
        self.btn_exec_tasks.setEnabled(True)
        self.update_memory_ui()
        self.scan_processes()
        self.log(f"✅ {msg}")

    def scan_processes(self):
        if is_worker_running(self.proc_worker):
            return
        self.proc_worker = ProcessScannerWorker()
        self.proc_worker.processes_ready.connect(self.populate_process_table)
        self.proc_worker.finished.connect(self._on_proc_worker_finished)
        self.proc_worker.start()

    def _on_proc_worker_finished(self):
        if self.proc_worker:
            self.proc_worker.deleteLater()
            self.proc_worker = None

    def populate_process_table(self, procs: List[Dict[str, Any]]):
        self.all_processes = procs
        for row in range(self.table_procs.rowCount()):
            w = self.table_procs.cellWidget(row, 0)
            if w is not None:
                w.deleteLater()
        self.table_procs.clearContents()
        self.apply_proc_filter()

    def apply_proc_filter(self):
        filter_idx = self.combo_proc_filter.currentIndex()
        filtered = []

        for p in self.all_processes:
            cmd = p["cmd_full"].lower()
            if filter_idx == 0:  # Todos
                filtered.append(p)
            elif filter_idx == 1 and any(b in cmd for b in ["chrome", "brave", "firefox", "chromium"]):
                filtered.append(p)
            elif filter_idx == 2 and any(k in cmd for k in ["python", "node", "npm", "uvx"]):
                filtered.append(p)
            elif filter_idx == 3 and any(k in cmd for k in ["ollama", "torch", "vllm", "cuda"]):
                filtered.append(p)
            elif filter_idx == 4 and any(k in cmd for k in ["mcp", "syncthing", "playwright"]):
                filtered.append(p)

        checked_pids = {pid for pid, cb in self.table_checkboxes.items() if cb.isChecked()}

        self.table_procs.setRowCount(len(filtered))
        self.table_checkboxes.clear()

        for row, p in enumerate(filtered):
            pid = p["pid"]

            cb = QCheckBox()
            if pid in checked_pids:
                cb.setChecked(True)
            self.table_checkboxes[pid] = cb
            
            cb_container = QWidget()
            cb_lay = QHBoxLayout(cb_container)
            cb_lay.addWidget(cb)
            cb_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lay.setContentsMargins(0, 0, 0, 0)
            self.table_procs.setCellWidget(row, 0, cb_container)

            item_pid = QTableWidgetItem(pid)
            item_pid.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            self.table_procs.setItem(row, 1, item_pid)

            item_cmd = QTableWidgetItem(f"{p['cmd_short']}  ({p['cmd_full'][:75]})")
            item_cmd.setToolTip(p["cmd_full"])
            self.table_procs.setItem(row, 2, item_cmd)

            item_mem = QTableWidgetItem(f"{p['mem']}%")
            item_mem.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_procs.setItem(row, 3, item_mem)

            item_mb = QTableWidgetItem(f"{p['mb']} MB")
            item_mb.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            item_mb.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table_procs.setItem(row, 4, item_mb)

            item_cpu = QTableWidgetItem(f"{p['cpu']}%")
            item_cpu.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_procs.setItem(row, 5, item_cpu)

            item_user = QTableWidgetItem(p["user"])
            item_user.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_procs.setItem(row, 6, item_user)

    def toggle_all_proc_checks(self, checked: bool):
        for cb in self.table_checkboxes.values():
            cb.setChecked(checked)

    def kill_selected_processes(self):
        selected_pids = [pid for pid, cb in self.table_checkboxes.items() if cb.isChecked()]
        if not selected_pids:
            QMessageBox.warning(self, "Sin Selección", "No has marcado ningún proceso para terminar.")
            return

        msg = (
            f"¿Estás seguro de terminar {len(selected_pids)} procesos seleccionados?\n\n"
            f"PIDs: {', '.join(selected_pids[:10])}{'...' if len(selected_pids) > 10 else ''}\n"
            f"Se enviará señal SIGTERM / SIGKILL de forma cooperativa con psutil en segundo plano."
        )

        reply = QMessageBox.question(
            self,
            "Confirmar Terminación",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if is_worker_running(self.action_worker):
                return
            self.log(f"⏳ Terminando {len(selected_pids)} procesos en segundo plano...")
            self.action_worker = ProcessActionWorker("kill", selected_pids)
            self.action_worker.action_finished.connect(self._on_action_finished)
            self.action_worker.finished.connect(self._on_action_worker_finished)
            self.action_worker.start()

    def restart_selected_service(self):
        selected_pids = [pid for pid, cb in self.table_checkboxes.items() if cb.isChecked()]
        if not selected_pids:
            QMessageBox.warning(self, "Sin Selección", "Selecciona al menos un proceso para reiniciar.")
            return

        if is_worker_running(self.action_worker):
            return

        extra_map = {}
        for pid in selected_pids:
            proc = next((p for p in self.all_processes if p["pid"] == pid), None)
            if proc:
                extra_map[pid] = proc["cmd_short"]

        self.log("⏳ Reiniciando servicios seleccionados en segundo plano...")
        self.action_worker = ProcessActionWorker("restart_service", selected_pids, extra_map)
        self.action_worker.action_finished.connect(self._on_action_finished)
        self.action_worker.finished.connect(self._on_action_worker_finished)
        self.action_worker.start()

    def _on_action_worker_finished(self):
        if self.action_worker:
            self.action_worker.deleteLater()
            self.action_worker = None

    def _on_action_finished(self, msg: str):
        self.log(f"✅ {msg}")
        QTimer.singleShot(400, self.scan_processes)
        QTimer.singleShot(500, self.update_memory_ui)

    def cleanup(self):
        """Detiene timers y workers de forma determinista y cooperativa sin terminate()."""
        if self.mem_timer is not None:
            self.mem_timer.stop()
            self.mem_timer = None
        if self.proc_timer is not None:
            self.proc_timer.stop()
            self.proc_timer = None

        for worker in (self.opt_worker, self.proc_worker, self.action_worker):
            stop_worker(worker, timeout_ms=1800)
        self.opt_worker = None
        self.proc_worker = None
        self.action_worker = None
