# gestor-facturas

Asistente personal de finanzas basado en agente. Permite fotografiar facturas físicas o digitales y registrarlas en una base de datos SQLite local, usando la línea de comandos (CLI).

Proyecto de la maestría MISIA (Cenfotec), curso IA distribuida.

## Descripción

El agente ejecuta un pipeline de seis pasos por factura:

1. Extracción de texto con OCR basado en un LLM con visión (OpenAI GPT-4o o Anthropic Claude, configurable).
2. Validación de campos obligatorios, fecha, moneda y coherencia aritmética.
3. Validación de la categoría contra una lista cerrada.
4. Detección de duplicados.
5. Confirmación explícita del usuario (con confirmación adicional para montos altos).
6. Registro de la transacción en SQLite.

El servidor MCP `finanzas-mcp` es un guardián de escritura independiente. Revalida todos los datos y no confía en el agente. El texto extraído por OCR se trata siempre como dato no confiable, como defensa contra inyecciones indirectas en las imágenes.

Fuera de alcance: ingresos, gastos fijos, app móvil e interfaces gráficas. Se procesa una imagen por factura.

## Arquitectura

| Componente | Ruta | Función |
|---|---|---|
| Lógica de negocio | `finanzas_mcp/business/` | Validaciones, duplicados y transacciones. No depende de MCP ni de stdin/stdout. |
| Capa de datos | `finanzas_mcp/db/` | Esquema y repositorio SQLite. |
| Servidor finanzas-mcp | `finanzas_mcp/server.py` | Herramientas `validar_factura`, `buscar_duplicados`, `listar_transacciones`, `registrar_transaccion`. |
| Servidor ocr-mcp | `ocr_mcp/` | Herramienta `ocr_imagen` con confinamiento de rutas y cliente OpenAI/Anthropic. |
| Agente | `agent/` | Pipeline SKILL (`agent.py`), CLI (`main.py`), trazador y `SKILL.md`. |
| Política | `politica.json` | Herramientas permitidas, límites de pasos y tokens, umbrales. |
| Evaluación y seguridad | eval/, security/ | Conjunto etiquetado de 45 facturas y plantilla de análisis de inyección. |

## Estado actual

Implementado: capa SQLite, modelos, validaciones, duplicados, transacciones, servidores `finanzas-mcp` y `ocr-mcp`, cliente OCR (OpenAI o Anthropic), trazador, política, pipeline SKILL de seis pasos, CLI (`agent/main.py`), pruebas unitarias R1 a R11, estructura del conjunto de evaluación (`eval/`), plantilla de análisis de seguridad (`security/`) y Docker.

Pendiente: pruebas de propiedad opcionales (Hypothesis) de varias secciones, etiquetado real del conjunto de evaluación y ejecución del análisis de inyección. Ver `.kiro/specs/gestor-facturas/tasks.md`.

Nota: con `mcp` 1.9.1 y pydantic 2.14.x la importación de `mcp` puede fallar (`eval_type_backport`). Si ocurre, fije una versión de pydantic compatible.
## Requisitos

- Python 3.10 o superior
- Gestor de paquetes `pip`
- Una clave de OpenAI (`OPENAI_API_KEY`) o de Anthropic (`ANTHROPIC_API_KEY`) para el OCR
- Node.js (opcional, solo para el inspector de MCP)

## Ejecución

Todos los comandos se ejecutan desde esta carpeta (`Backend`).

### 1. Crear el entorno e instalar dependencias

Con pip (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Con pip (bash: Linux, macOS o Git Bash en Windows):

```bash
python3 -m venv .venv
source .venv/bin/activate        # en Git Bash en Windows: source .venv/Scripts/activate
pip install -r requirements.txt
```

### 2. Variables de entorno

```powershell
$env:OPENAI_API_KEY = "tu-clave"      # OCR con OpenAI (o ANTHROPIC_API_KEY)
$env:LLM_PROVIDER = "openai"          # openai | anthropic (opcional; se detecta por la clave)
$env:OCR_MODEL = "gpt-4o"            # opcional; por defecto gpt-4o / claude-3-5-sonnet-latest
$env:DB_PATH = "./data/facturas.db"   # base de datos SQLite
$env:MCP_USER_ID = "usuario_prueba"   # usuario de la sesión
$env:INVOICES_DIR = "./facturas"      # carpeta permitida para imágenes
```

### 3. Ejecutar las pruebas

```powershell
python -m unittest discover -s tests -v
```

También funciona `python -m pytest tests -v`. En PowerShell puede aparecer ruido de `RemoteException`. Es solo cosmético; lo importante es el `OK` final.

### 4. Levantar el servidor finanzas-mcp

```powershell
python -m finanzas_mcp.server
```

Para probarlo de forma interactiva con el inspector de MCP:

```powershell
npx @modelcontextprotocol/inspector python -m finanzas_mcp.server
```

### 5. Ejecutar el agente

```powershell
python -m agent.main .\facturas\mi_factura.jpg
```

Los prompts de confirmación se muestran en pantalla y las respuestas se leen del teclado. Al final se imprime el resultado y la razón de parada. Las trazas se guardan en `traces/`. Códigos de salida: 0 éxito, 1 error de validación o arranque, 2 cancelado por el usuario, 3 límite de pasos o tokens.

### 6. Docker

```powershell
docker compose up --build
```

El compose monta `./data` (base de datos) en `/app/data` y `./facturas` en `/app/facturas`, y define `DB_PATH` e `INVOICES_DIR`. Las claves se leen de un archivo `.env`.

## Proveedor de LLM

| Variable | Descripción |
|---|---|
| `LLM_PROVIDER` | `openai` o `anthropic`. Si falta, usa Anthropic solo cuando existe `ANTHROPIC_API_KEY` y no `OPENAI_API_KEY`; si no, OpenAI. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Clave del proveedor elegido. |
| `OCR_MODEL` | Modelo con visión. Por defecto `gpt-4o` (OpenAI) o `claude-3-5-sonnet-latest` (Anthropic). |