# FUENTE 5: INTEGRACIÓN DE CLAUDE CODE CLI, MULTI-PROVEEDOR Y SERVIDORES MCP REMOTOS
**Base de Verdad Canónica para Google NotebookLM — Ecosistema FloydIA v27**
*Fecha: 2026-08-31 | Protocolo: v27 | Autor: Antigravity Agent*

---

## 1. Contexto y Arquitectura de Claude Code CLI

Claude Code CLI (`@anthropic-ai/claude-code`) v2.1.251 se integró como el 5º agente oficial del ecosistema FloydIA (junto a Antigravity IDE, OpenCode, Hermes CLI y Zed), operando bajo las directivas de arquitectura SRE para equipos legacy (HP15 / Arch Linux).

### Principios Fundamentales:
- **0% Resident Daemons**: Cero consumo de RAM en reposo. Claude Code se invoca como binario interactivo on-demand.
- **Aislamiento de Secretos**: Ningún token o API key se almacena en texto plano en archivos de configuración persistidos. Las credenciales se inyectan en memoria al momento de la ejecución desde `/home/tec/.secrets/antigravity.env` (`chmod 600`).
- **Compatibilidad Multi-Proveedor Dinámica**: Soporte nativo para operar con modelos Anthropic directos, o redirigir el tráfico hacia proveedores compatibles (OpenRouter, DeepSeek, AeroLink, EvoLink).

---

## 2. Orquestación y Lanzador Multi-Proveedor (`launch_claude.sh`)

Ubicación: `SCRIPTS/launch_claude.sh` (enlazado simbólicamente a `~/.local/bin/claude`).

### Modos de Ejecución Disponibles:
```bash
claude                # Inicia con Anthropic Direct API (modelo claude-3-7-sonnet)
claude --anthropic    # Fuerza credencial directa Anthropic
claude --openrouter   # Enruta vía OpenRouter API (ANTHROPIC_BASE_URL)
claude --aerolink     # Enruta vía AeroLink Proxy API
claude --evolink      # Enruta vía EvoLink Gateway
claude --deepseek     # Enruta vía DeepSeek R1 / Coder
claude --menu         # Despliega selector interactivo TUI de proveedor
```

### Implementación del Wrapper de Inyección Segura:
```bash
#!/usr/bin/env bash
# launch_claude.sh — Inyección segura en memoria y multi-proveedor
ENV_FILE="/home/tec/.secrets/antigravity.env"
if [ -f "$ENV_FILE" ]; then
    export ANTHROPIC_API_KEY=$(grep -E '^ANTHROPIC_API_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    export OPENROUTER_API_KEY=$(grep -E '^OPENROUTER_API_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
fi

case "$1" in
    --openrouter)
        export ANTHROPIC_BASE_URL="https://openrouter.ai/api/v1"
        export ANTHROPIC_API_KEY="$OPENROUTER_API_KEY"
        shift
        ;;
    --deepseek)
        export ANTHROPIC_BASE_URL="https://api.deepseek.com/v1"
        shift
        ;;
esac

exec ~/.npm-global/bin/claude "$@"
```

---

## 3. Gobernanza y Reglas de Workspace (`CLAUDE.md`)

Para garantizar paridad de comportamiento y adhesión estricta a las directivas globales, se definió `CLAUDE.md` en la raíz del workspace:

1. **Regla Inmutable de Idioma**: Respuestas SIEMPRE en español en toda comunicación, resúmenes, auditorías e informes técnicos.
2. **Compuerta de Memoria Obligatoria**: Secuencia de 3 pasos (Graphify AST -> Escaneo Anti-Reincidencia -> Ground Truth Check) antes de emitir modificaciones o tool calls de escritura.
3. **Denylist de Comandos Destructivos**: Prohibición explícita de `rm -rf` fuera de `scratch/`, `dd`, `mkfs`, force-pushes y despliegues directos a producción sin staging.
4. **Verificación Visual Anclada**: Obligatoriedad de citar screenshot `.png` + SHA256 + JSON de aserciones de Playwright antes de certificar cualquier componente frontend o despliegue.

---

## 4. Sincronización Automática de Perfiles MCP (`mcp-select`)

La integración con el selector de perfiles MCP (`SCRIPTS/mcp_profile_selector.py`) permite que al cambiar de perfil de trabajo (`default`, `web-deploy`, `research`, `visual-design`), el archivo de configuración `~/.claude.json` se actualice de forma sincronizada con el resto de agentes.

### Mapeo de Paridad en 5 Agentes (`SCRIPTS/verify_multiagent_parity.py`):
- **Antigravity IDE**: `~/.gemini/config/mcp_config.json`
- **OpenCode**: `~/.config/opencode/opencode.jsonc`
- **Hermes CLI**: `~/.hermes/config.yaml`
- **Zed Editor**: `~/.config/zed/settings.json`
- **Claude Code**: `~/.claude.json`

---

## 5. Servidores MCP Remotos: WordPress Block Editor & Novamira

Se configuró el transporte remoto `@automattic/mcp-wordpress-remote` para interactuar directamente con instalaciones WordPress sin necesidad de plugins pesados de sincronización.

### Caso de Uso: Coquita Crochet (`https://coquita.site`)
- **Transporte**: `npx -y @automattic/mcp-wordpress-remote@latest`
- **Servidor Registrado**: `novamira-coquita-site`
- **Capacidades**: 48 habilidades (*abilities*) descubiertas para gestión de posts, taxonomías, metadatos, bloques de Gutenberg y media library.
- **Autenticación**: Application Passwords de WordPress gestionadas vía variables de entorno cargadas con `load_mcp_env.sh` (modo literal, preservando caracteres especiales).
