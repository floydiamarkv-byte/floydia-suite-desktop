#!/usr/bin/env python3
"""
FLOYDIA Reboot Hub — Motor de Ejecución y Telemetría de Red (PROTOCOLO v26)
Gestiona la verificación de estado (Pre-Flight Health Check) y el reinicio
ordenado y seguro de los nodos de la infraestructura.
"""

import os
import sys
import time
import json
import socket
import subprocess
import threading
from typing import Dict, Any, List, Tuple, Callable, Optional

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(WORKSPACE_ROOT, ".env")
CONFIG_PATH = os.path.join(WORKSPACE_ROOT, "SCRIPTS", "restart_nodes_config.json")


def load_env_safely() -> Dict[str, str]:
    """Carga variables del archivo .env sin exponer secretos."""
    env_vars = {}
    if not os.path.exists(ENV_PATH):
        return env_vars
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("#") or "=" not in line_str:
                    continue
                parts = line_str.split("=", 1)
                k = parts[0].strip()
                v = parts[1].strip().strip('"').strip("'")
                env_vars[k] = v
    except Exception as e:
        print(f"[WARN] Error al leer .env: {e}", file=sys.stderr)
    return env_vars


def get_resolved_node(node: Dict[str, Any], env_map: Dict[str, str]) -> Dict[str, Any]:
    """Resuelve IPs, puertos y credenciales desde .env con valores fallback y soporte de prefijos S##_."""
    resolved = dict(node)
    
    def resolve_key(key_name: Optional[str], default_val: Any) -> Any:
        if not key_name:
            return default_val
        # 1. Búsqueda exacta
        if key_name in env_map and env_map[key_name]:
            return env_map[key_name]
        # 2. Búsqueda normalizada (ignorando o añadiendo prefijo S##_)
        clean_key = key_name.split("_", 1)[-1] if key_name.startswith("S") and "_" in key_name else key_name
        for k, v in env_map.items():
            if not v:
                continue
            k_clean = k.split("_", 1)[-1] if k.startswith("S") and "_" in k else k
            if k == clean_key or k_clean == clean_key or k.endswith(f"_{clean_key}"):
                return v
        return default_val

    resolved["ip"] = resolve_key(node.get("ip_env_key"), node.get("default_ip", "127.0.0.1"))
    resolved["user"] = resolve_key(node.get("user_env_key"), node.get("default_user", "root"))
    resolved["password"] = resolve_key(node.get("pass_env_key"), "")
    return resolved


def ping_host(ip: str, timeout_sec: float = 1.5) -> Tuple[bool, float]:
    """Ejecuta un ping ICMP rápido para medir disponibilidad y latencia."""
    if ip in ["127.0.0.1", "localhost"]:
        return True, 0.1
    try:
        t_start = time.perf_counter()
        res = subprocess.run(
            ["ping", "-c", "1", "-W", str(max(1, int(timeout_sec))), ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        latency = (time.perf_counter() - t_start) * 1000.0
        if res.returncode == 0:
            return True, round(latency, 1)
        return False, -1.0
    except Exception:
        return False, -1.0


def check_tcp_port(ip: str, port: int, timeout_sec: float = 1.5) -> bool:
    """Verifica si un puerto TCP específico está abierto y respondiendo."""
    if not port:
        return True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout_sec)
            res = s.connect_ex((ip, port))
            return res == 0
    except Exception:
        return False


def check_node_health(node: Dict[str, Any], env_map: Dict[str, str]) -> Dict[str, Any]:
    """Realiza el Pre-Flight Health Check completo de un nodo."""
    resolved = get_resolved_node(node, env_map)
    ip = resolved["ip"]
    port = node.get("check_port")
    
    is_ping_ok, latency = ping_host(ip)
    is_port_ok = check_tcp_port(ip, port) if (is_ping_ok and port) else (is_ping_ok if not port else False)
    
    status_text = "ONLINE" if (is_ping_ok and (not port or is_port_ok)) else ("INACCESIBLE" if not is_ping_ok else "PUERTO CERRADO")
    return {
        "id": node["id"],
        "name": node["name"],
        "ip": ip,
        "port": port,
        "ping_ok": is_ping_ok,
        "port_ok": is_port_ok,
        "latency_ms": latency,
        "status": status_text
    }


def _get_clean_env() -> Dict[str, str]:
    """Retorna variables de entorno libres de contaminación por AppImages."""
    clean = os.environ.copy()
    clean.pop("LD_LIBRARY_PATH", None)
    clean.pop("PYTHONHOME", None)
    clean.pop("PYTHONPATH", None)
    clean.pop("QT_PLUGIN_PATH", None)
    clean.pop("GTK_PATH", None)
    return clean


def _build_ssh_base(user: str, ip: str, pwd: str, timeout_sec: int = 6) -> List[str]:
    """Construye el comando SSH base según si hay contraseña (sshpass) o clave SSH."""
    base = [
        "ssh",
        "-o", f"ConnectTimeout={timeout_sec}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
    ]
    if pwd:
        return ["sshpass", "-p", pwd] + base
    else:
        return base + ["-o", "BatchMode=yes"]


def _is_reboot_disconnect(stderr_text: str, returncode: int) -> bool:
    """Detecta si el cierre de sesión SSH fue provocado por el reinicio del host remoto."""
    if returncode == 0:
        return True
    lower = stderr_text.lower()
    disconnect_indicators = [
        "connection closed",
        "closed by remote host",
        "connection reset",
        "broken pipe",
        "connection refused",
        "kex_exchange_identification",
        "banner exchange",
        "shutdown/reboot",
        "received disconnect",
        "disconnected from",
        "reboot",
        "shutdown",
        "disconnect",
        "closed",
    ]
    return any(ind in lower for ind in disconnect_indicators)


def execute_reboot_node(
    node: Dict[str, Any],
    env_map: Dict[str, str],
    dry_run: bool = False,
    log_cb: Optional[Callable[[str, str], None]] = None
) -> Tuple[bool, str]:
    """
    Ejecuta el reinicio de un nodo específico de forma segura.
    Retorna (éxito, mensaje_detalle).
    """
    def log(msg: str, level: str = "INFO"):
        if log_cb:
            log_cb(msg, level)
        else:
            print(f"[{level}] {msg}")

    resolved = get_resolved_node(node, env_map)
    n_id = resolved["id"]
    n_name = resolved["name"]
    n_type = resolved.get("type", "ssh_linux")
    ip = resolved["ip"]
    user = resolved["user"]
    pwd = resolved["password"]
    
    log(f"Iniciando proceso para '{n_name}' ({ip}) [Tipo: {n_type}]...", "INFO")
    
    if dry_run:
        log(f"[SIMULACIÓN DRY-RUN] Enviando señal ficticia de reinicio a '{n_name}' ({ip})...", "INFO")
        time.sleep(1.2)
        log(f"[SIMULACIÓN DRY-RUN] '{n_name}' procesado con éxito (0 cambios reales).", "SUCCESS")
        return True, "Simulación completada con éxito"

    log(f"[MODO REAL] ⚡ Ejecutando orden de reinicio real para '{n_name}' ({ip}) [Tipo: {n_type}]...", "WARN")

    clean_env = _get_clean_env()

    # 1. Proxmox VE Server
    if n_type == "proxmox":
        try:
            log(f"Conectando a Proxmox ({ip})...", "INFO")
            ssh_cmd = _build_ssh_base(user, ip, pwd, timeout_sec=6) + [f"{user}@{ip}", "systemctl reboot || reboot"]
            
            res = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8, env=clean_env)
            if res.returncode == 0 or _is_reboot_disconnect(res.stderr, res.returncode):
                log(f"Comando de reinicio enviado a Proxmox ({ip}).", "SUCCESS")
                return True, "Reinicio enviado a Proxmox"
            else:
                err_msg = res.stderr.strip() or f"Código de retorno {res.returncode}"
                log(f"Error en SSH a Proxmox: {err_msg}", "ERROR")
                return False, err_msg
        except subprocess.TimeoutExpired:
            log(f"Timeout al esperar respuesta de Proxmox (esperado tras el corte de reboot).", "SUCCESS")
            return True, "Reinicio enviado a Proxmox (conexión cerrada)"
        except Exception as e:
            log(f"Error al reiniciar Proxmox: {e}", "ERROR")
            return False, str(e)

    # 2. HP45 (Linux SSH - MX Linux / Debian)
    elif n_type == "ssh_linux":
        try:
            log(f"Enviando orden de reinicio a {n_name} ({user}@{ip})...", "INFO")
            remote_cmd = "sudo -n reboot || sudo -n shutdown -r now || sudo systemctl reboot || reboot"
            ssh_cmd = _build_ssh_base(user, ip, pwd, timeout_sec=5) + [f"{user}@{ip}", remote_cmd]
            
            res = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=7, env=clean_env)
            if res.returncode == 0 or _is_reboot_disconnect(res.stderr, res.returncode):
                log(f"Orden de reinicio aceptada por {n_name}.", "SUCCESS")
                return True, f"Reinicio enviado a {n_name}"
            else:
                err_msg = res.stderr.strip() or f"Código de retorno {res.returncode}"
                log(f"Error en SSH hacia {n_name}: {err_msg}", "ERROR")
                return False, err_msg
        except subprocess.TimeoutExpired:
            log(f"Conexión con {n_name} finalizada (reinicio en curso).", "SUCCESS")
            return True, f"Reinicio ejecutado en {n_name}"
        except Exception as e:
            log(f"Fallo en SSH hacia {n_name}: {e}", "ERROR")
            return False, str(e)

    # 3. MikroTik Router & AP
    elif n_type == "mikrotik":
        try:
            log(f"Enviando comando RouterOS '/system reboot' a {n_name} ({ip})...", "INFO")
            script_reboot = "/system reboot"
            ssh_cmd = _build_ssh_base(user, ip, pwd, timeout_sec=6) + [f"{user}@{ip}", script_reboot]
            
            proc = subprocess.Popen(ssh_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=clean_env)
            try:
                out, err = proc.communicate(input="y\n", timeout=6)
                if proc.returncode == 0 or _is_reboot_disconnect(err, proc.returncode):
                    log(f"Comando RouterOS enviado a {n_name} ({ip}).", "SUCCESS")
                    return True, f"Reinicio enviado a {n_name}"
                else:
                    err_msg = err.strip() or f"Código de retorno {proc.returncode}"
                    log(f"Error en RouterOS hacia {n_name}: {err_msg}", "ERROR")
                    return False, err_msg
            except subprocess.TimeoutExpired:
                proc.kill()
                log(f"MikroTik {n_name} cerró el socket (reinicio iniciado).", "SUCCESS")
                return True, f"Reinicio enviado a {n_name}"
        except Exception as e:
            log(f"Error al enviar reboot a MikroTik {n_name}: {e}", "ERROR")
            return False, str(e)

    # 4. TP-Link AP
    elif n_type == "tplink":
        try:
            log(f"Enviando solicitud de reinicio a TP-Link AP ({ip})...", "INFO")
            ssh_cmd = _build_ssh_base(user, ip, pwd, timeout_sec=4) + [f"{user}@{ip}", "reboot || /sbin/reboot"]
            
            proc = subprocess.Popen(ssh_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=clean_env)
            try:
                proc.communicate(timeout=5)
                log(f"Señal de reinicio enviada a TP-Link AP ({ip}).", "SUCCESS")
                return True, "Reinicio enviado a TP-Link AP"
            except subprocess.TimeoutExpired:
                proc.kill()
                log(f"Socket de TP-Link cerrado (reinicio en proceso).", "SUCCESS")
                return True, "Reinicio enviado a TP-Link AP"
        except Exception as e:
            log(f"Aviso TP-Link: {e}. Se continúa con la secuencia.", "WARN")
            return True, "Reinicio TP-Link emitido"

    # 5. Localhost HP15 (Debian 13 SysVinit / Sudo NOPASSWD)
    elif n_type == "localhost":
        log("🚨 PREPARANDO REINICIO LOCAL DEL HOST HP15...", "WARN")
        log("Ejecutando reinicio determinista de HP15 (sin bloqueos de red ni pantallas colgadas)...", "INFO")
        try:
            cmd = ["sudo", "/usr/local/bin/hp15-safe-reboot.sh"]
            subprocess.Popen(cmd, env=clean_env)
            return True, "Reinicio limpio de HP15 emitido"
        except Exception as e:
            log(f"Aviso con hp15-safe-reboot: {e}. Intentando reboot -f...", "WARN")
            try:
                subprocess.Popen(["sudo", "-n", "reboot", "-f"], env=clean_env)
                return True, "Reinicio forzado de HP15 emitido"
            except Exception as e2:
                log(f"Error al reiniciar localmente: {e2}", "ERROR")
                return False, str(e2)

    return False, "Tipo de nodo desconocido"
