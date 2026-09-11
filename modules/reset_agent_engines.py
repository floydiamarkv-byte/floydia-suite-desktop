#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reset_agent_engines.py — Restablece los motores y modelos de los agentes a configuración por defecto
FloydIA Protocolo v28 | Ecosistema Agéntico HP15/HP45

Permite purgar de manera selectiva o global las APIs y motores programados en:
- OpenCode (~/.config/opencode/opencode.jsonc)
- Hermes Agent (~/.hermes/config.yaml & provider_models_cache.json)
- DeepSeek Harness (~/.dsh/ & SCRIPTS/dsh-settings.yaml)
- Zed Editor (~/.config/zed/settings.json)
- Antigravity IDE (~/.config/Antigravity IDE/User/settings.json)
- Caché Local FloydIA Suite (cache/custom_apis.json)

Regla de Oro: PRESERVA ÍNTEGRAMENTE los servidores y herramientas MCP (mcp: { ... }).
Genera respaldos .bak-<timestamp> antes de cualquier modificación.
"""

import os
import sys
import json
import shutil
import time
import argparse
from datetime import datetime
from typing import Dict, List, Any, Tuple

def get_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def backup_file(path: str) -> str:
    if os.path.exists(path):
        ts = get_timestamp()
        bak_path = f"{path}.bak-{ts}"
        shutil.copy2(path, bak_path)
        return bak_path
    return ""

def load_json_or_jsonc(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Intento 1: json estándar
    try:
        return json.loads(content)
    except Exception:
        pass
    
    # Intento 2: parsear eliminando comentarios sencillos
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except Exception:
        return {}

def reset_opencode() -> Tuple[bool, str]:
    """Restablece OpenCode eliminando proveedores y modelos custom pero preservando MCPs."""
    target = os.path.expanduser("~/.config/opencode/opencode.jsonc")
    bak = ""
    if os.path.exists(target):
        bak = backup_file(target)
        data = load_json_or_jsonc(target)
    else:
        data = {}

    mcp_block = data.get("mcp", {})
    schema = data.get("$schema", "https://opencode.ai/config.json")

    clean_cfg = {
        "$schema": schema
    }
    if mcp_block:
        clean_cfg["mcp"] = mcp_block

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(clean_cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # También limpiar workspace .opencode si existe
    ws_opencode = os.path.expanduser("~/Dropbox/ANTIGRAVITY_PROJECTS/.opencode/opencode.json")
    if os.path.exists(ws_opencode):
        backup_file(ws_opencode)
        ws_data = load_json_or_jsonc(ws_opencode)
        ws_clean = {"$schema": ws_data.get("$schema", "https://opencode.ai/config.json")}
        if "mcp" in ws_data:
            ws_clean["mcp"] = ws_data["mcp"]
        with open(ws_opencode, "w", encoding="utf-8") as f:
            json.dump(ws_clean, f, indent=2, ensure_ascii=False)
            f.write("\n")

    msg = f"OpenCode restablecido a configuración limpia (MCPs preservados)."
    if bak:
        msg += f" Respaldo: {os.path.basename(bak)}"
    return True, msg

def reset_hermes() -> Tuple[bool, str]:
    """Restablece Hermes Agent eliminando providers custom y purgando caché."""
    target = os.path.expanduser("~/.hermes/config.yaml")
    cache_file = os.path.expanduser("~/.hermes/provider_models_cache.json")
    bak = ""
    
    if os.path.exists(target):
        bak = backup_file(target)
    
    clean_hermes = """# Hermes Agent — Configuración limpia por defecto
# Generado por FloydIA Suite (Reset a Defecto)
model:
  default: gemini-2.0-flash
  provider: google
providers: {}
database:
  journal_mode: wal
runtime:
  nofile_soft_limit: 4096
"""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(clean_hermes)
    
    if os.path.exists(cache_file):
        backup_file(cache_file)
        try:
            os.remove(cache_file)
        except Exception:
            pass

    msg = "Hermes restablecido a configuración por defecto (caché purgada)."
    if bak:
        msg += f" Respaldo: {os.path.basename(bak)}"
    return True, msg

def reset_dsh() -> Tuple[bool, str]:
    """Restablece DeepSeek Harness (DSH) eliminando proveedores inyectados en llm-pi-ai."""
    target = os.path.expanduser("~/Dropbox/ANTIGRAVITY_PROJECTS/SCRIPTS/dsh-settings.yaml")
    bak = ""
    if os.path.exists(target):
        bak = backup_file(target)
    
    clean_dsh = """# DeepSeek Harness (DSH) — Configuración Limpia por Defecto
version: 2
default_provider: "google"
default_model: "gemini-2.0-flash"
theme: dark
agent-default-model:
  provider: deepseek-official
  model: deepseek-chat
  reasoningEffort: medium
llm-pi-ai:
  providers: {}
"""
    with open(target, "w", encoding="utf-8") as f:
        f.write(clean_dsh)
    
    # También limpiar ~/.dsh/ si contiene configuraciones de modelo
    dsh_home_cfg = os.path.expanduser("~/.dsh/settings.yaml")
    if os.path.exists(dsh_home_cfg):
        backup_file(dsh_home_cfg)
        with open(dsh_home_cfg, "w", encoding="utf-8") as f:
            f.write(clean_dsh)

    msg = "DeepSeek Harness restablecido a configuración por defecto."
    if bak:
        msg += f" Respaldo: {os.path.basename(bak)}"
    return True, msg

def reset_zed() -> Tuple[bool, str]:
    """Restablece Zed Editor eliminando el bloque 'agent' personalizado."""
    target = os.path.expanduser("~/.config/zed/settings.json")
    bak = ""
    if not os.path.exists(target):
        return True, "Zed Editor no tiene archivo settings.json (ya está por defecto)."
    
    bak = backup_file(target)
    data = load_json_or_jsonc(target)
    if "agent" in data:
        del data["agent"]
    
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    msg = "Zed Editor restablecido a motores nativos por defecto."
    if bak:
        msg += f" Respaldo: {os.path.basename(bak)}"
    return True, msg

def reset_antigravity() -> Tuple[bool, str]:
    """Restablece configuraciones de modelos custom en Antigravity IDE."""
    target = os.path.expanduser("~/.config/Antigravity IDE/User/settings.json")
    bak = ""
    if not os.path.exists(target):
        return True, "Antigravity IDE no tiene sobreescrituras en settings.json."
    
    bak = backup_file(target)
    data = load_json_or_jsonc(target)
    # Limpiar claves que modifiquen modelos de LLMs externos si existiesen
    keys_to_remove = [k for k in data.keys() if "model" in k.lower() or "ai_endpoint" in k.lower()]
    for k in keys_to_remove:
        del data[k]
    
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    msg = "Antigravity IDE configuración de modelos limpia."
    if bak:
        msg += f" Respaldo: {os.path.basename(bak)}"
    return True, msg

def reset_floydia_cache() -> Tuple[bool, str]:
    """Restablece la caché local de APIs registradas en FloydIA Suite."""
    cache_path = os.path.expanduser("~/Dropbox/ANTIGRAVITY_PROJECTS/FLOYDIA/SUBTOOLS/FLOYDIA_SUITE_2.0/cache/custom_apis.json")
    bak = ""
    if os.path.exists(cache_path):
        bak = backup_file(cache_path)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
    
    msg = "Caché de APIs de FloydIA Suite vaciada."
    if bak:
        msg += f" Respaldo: {os.path.basename(bak)}"
    return True, msg

RESET_DISPATCHER = {
    "opencode": ("OpenCode", reset_opencode),
    "hermes": ("Hermes Agent", reset_hermes),
    "dsh": ("DeepSeek Harness (DSH)", reset_dsh),
    "zed": ("Zed Editor", reset_zed),
    "antigravity": ("Antigravity IDE", reset_antigravity),
    "floydia_cache": ("Caché FloydIA Suite", reset_floydia_cache)
}

def execute_resets(selected_keys: List[str]) -> List[Tuple[str, bool, str]]:
    results = []
    for key in selected_keys:
        if key in RESET_DISPATCHER:
            name, func = RESET_DISPATCHER[key]
            try:
                ok, msg = func()
                results.append((name, ok, msg))
            except Exception as e:
                results.append((name, False, f"Error: {e}"))
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restablece motores de agentes a valores por defecto")
    parser.add_argument("--agents", nargs="+", choices=list(RESET_DISPATCHER.keys()), help="Agentes a restablecer")
    parser.add_argument("--all", action="store_true", help="Restablecer todos los agentes soportados")
    args = parser.parse_args()

    targets = list(RESET_DISPATCHER.keys()) if args.all else (args.agents or [])
    if not targets:
        print("Uso: python3 reset_agent_engines.py --all | --agents opencode hermes dsh zed antigravity")
        sys.exit(1)

    print("🔄 Ejecutando restablecimiento determinista...")
    res = execute_resets(targets)
    for name, ok, msg in res:
        icon = "✅" if ok else "❌"
        print(f"  {icon} [{name}]: {msg}")
