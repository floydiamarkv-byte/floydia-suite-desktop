# FUENTE 4: CATÁLOGO DE ANTI-PATRONES Y LECCIONES APRENDIDAS
**Prevención de Errores Críticos, Fugas de Contexto y Reglas Inmutables de Ingeniería Agéntica**
*Fecha de Consolidación: 2026-08-31 | Versión: 2.0.4 | Protocolo v27*

---

## 1. Catálogo de Anti-Patrones Vetados (#vetado)

A partir de la experiencia operativa acumulada en el Memory Bank (`lessons-learned.md`) y en incidentes reales de producción, se definen los siguientes anti-patrones con prohibición absoluta de reincidencia:

### 🚫 Anti-Patrón 1: Búsqueda Ciega Masiva (`grep -r` / `rg` en la Raíz)
- **Defecto**: Ejecutar comandos de búsqueda recursiva sin filtros sobre todo el workspace root (`rg foo .`), inundando el contexto con 50.000 tokens de bibliotecas `node_modules`, cachés `__pycache__` o archivos de log.
- **Solución Canónica**: Aplicar el **Protocolo de Resolución en 4 Niveles**:
  1. *Nivel 0*: `graphify query "<término>"` sobre la base SQLite (<10ms, 0 tokens masivos).
  2. *Nivel 1*: Cache inmediato (`.env`, `activeContext.md`, `techContext.md`).
  3. *Nivel 2*: Knowledge Vault Obsidian / NotebookLM.
  4. *Nivel 3*: `rg` quirúrgico acotado por extensión y subdirectorio (ej. `rg --glob '*.py' query SCRIPTS/`).

### 🚫 Anti-Patrón 2: Evasión de la Puerta de Memoria ("Resolver Primero, Justificar Después")
- **Defecto**: Modificar archivos en disco o proponer planes técnicos antes de haber consultado AST y escaneado anti-reincidencia.
- **Solución Canónica**: Declaración explícita y mecánica de los 3 pasos de la Compuerta de Memoria en el razonamiento antes de cualquier `tool_call` de escritura:
  ```
  Paso 1 ✅ (N resultados AST)
  Paso 2 ✅ (Sin coincidencias vetadas)
  Paso 3 ✅/N/A ...
  ```

### 🚫 Anti-Patrón 3: Certificación Sin Artefacto Visual ni Hash Criptográfico
- **Defecto**: Declarar que una página web, interfaz o servicio "funciona correctamente" o "QA PASS" basándose únicamente en un código de estado `HTTP 200` o la finalización sin error de un script.
- **Solución Canónica (Regla del Único Certificador)**: Prohibido dar por verificado un desarrollo frontend o UI sin citar:
  1. La ruta del screenshot `.png` capturado en CT114 tras renderizado real.
  2. El hash SHA256 del archivo de captura.
  3. El JSON de aserciones de Playwright (`qa_assertions.js --json`) con `pass: true`.

### 🚫 Anti-Patrón 4: Bucles de Reintento Infinitos (Anti-Loop Guardrail)
- **Defecto**: Repetir la misma llamada a herramienta o comando fallido más de 3 veces consecutivas con variaciones menores, consumiendo tokens innecesariamente.
- **Solución Canónica**: Límite estricto de **3 intentos con estrategias completamente distintas**. Si el tercer intento falla, registrar el bloqueo en `.session/negative_cache.json` y solicitar intervención humana.

### 🚫 Anti-Patrón 5: Fuga de Secretos en Logs y Artefactos
- **Defecto**: Volcar claves privadas, tokens Bearer o cadenas de conexión a base de datos en salidas de consola, reportes Markdown o prompts a modelos externos.
- **Solución Canónica**: Referenciar exclusivamente nombres de variables interpoladas `${VAR_NAME}` o marcadores enmascarados `••••••••`.

---

## 2. Lecciones Aprendidas Clave del Ecosistema FloydIA

| ID | Lección / Regla Operativa | Causa Raíz Histórica | Mecanismo Preventivo Implementado |
| :---: | :--- | :--- | :--- |
| **L07** | Metadatos SEO y semántica obligatorios en toda vista web. | Páginas creadas sin etiquetas OpenGraph ni JSON-LD. | Linter estático `lint_elementor_json.py` regla `E12`. |
| **L10** | Contenedores CSS con `overflow-x: hidden` y `box-sizing: border-box`. | Desbordamiento horizontal en pantallas móviles (375px). | Assertion automatizada `horizontalOverflow` en `qa_assertions.js`. |
| **L15** | Desacoplamiento de procesos pesados hacia CT114. | Saturación de memoria RAM y congelamiento de la GUI en HP15. | Servidor remoto Playwright en `ws://192.168.1.238:3000/playwright`. |
| **L21** | Validación de frescura de caché edge mediante marcadores ALT. | Hosts con caché agresiva servían versiones desactualizadas de HTML. | Test de marcador ALT (`qa_assertions.js --marker <str>`). |
| **L27** | Visibilidad del menú hamburguesa móvil en viewports ≤375px. | Botones de navegación ocultos por capas CSS z-index erróneas. | Validación obligatoria en viewport 375px en QA E5. |
| **L33** | Inspección visual obligatoria del screenshot antes de certificar. | Aserciones pasaban con HTML vacío pero fondo oscuro. | Inspección humana/visión del archivo `.png` antes del cierre de tarea. |

---

## 3. Matriz de Enrutamiento de Modelos y Token Economics

Para maximizar la relación calidad-precio y la velocidad de respuesta agéntica:

```
┌──────────────────────────────────────────────────────────────────────────┐
│                             TAREA ENTRANTE                               │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
  [TIER TRIVIAL]              [TIER ESTÁNDAR]             [TIER ARQUITECTURA]
• Linter estático           • Edición de código         • Diagnóstico complejo
• Grep / AST query          • Scripts Python            • Refactor estructural
• Formateo / Ping           • Despliegues / S2E         • Hardening de seguridad
         │                           │                           │
         ▼                           ▼                           ▼
  Gemini 2.0 Flash            Codestral Latest            DeepSeek Reasoner R1
  Qoder Lite (Free)           DeepSeek Chat V3            Gemini 2.5 Pro
  Qwen 2.5 Coder 7B           Qwen 2.5 Coder 32B          Claude Opus Thinking
```
