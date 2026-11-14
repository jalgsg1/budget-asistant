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

** Trabajo futuro
Ingresos, gastos fijos, app móvil e interfaz gráfica. Se procesa una imagen por factura.

## Arquitectura

| Componente | Ruta | Función |
|---|---|---|
| Lógica de negocio | `finanzas_mcp/business/` | Validaciones, duplicados y transacciones. No depende de MCP ni de stdin/stdout. |
| Capa de datos | `finanzas_mcp/db/` | Esquema y repositorio SQLite. |
| Servidor finanzas-mcp | `finanzas_mcp/server.py` | Herramientas `validar_factura`, `buscar_duplicados`, `listar_transacciones`, `registrar_transaccion`. |
| Servidor ocr-mcp | `ocr_mcp/` | Herramienta `ocr_imagen` con confinamiento de rutas y cliente OpenAI/Anthropic. |
| Agente | `agent/` | Pipeline SKILL (`agent.py`), CLI (`main.py`), trazador y `SKILL.md`. |
| Política | `politica.json` | Herramientas permitidas, límites de pasos y tokens, umbrales. |
| API de pruebas | `api_pruebas/` | API HTTP (FastAPI) para probar OCR, validación, listado, Pipeline y Batch sin la CLI. Ver sección más abajo. |
| Evaluación y seguridad | eval/, security/ | Conjunto etiquetado de 45 facturas y plantilla de análisis de inyección. |

## Estado actual

Implementado: capa SQLite, modelos, validaciones, duplicados, transacciones, servidores `finanzas-mcp` y `ocr-mcp`, cliente OCR (OpenAI o Anthropic), trazador, política, pipeline SKILL de seis pasos, CLI (`agent/main.py`), pruebas unitarias R1 a R11, estructura del conjunto de evaluación (`eval/`), plantilla de análisis de seguridad (`security/`), Docker y API de pruebas HTTP (`api_pruebas/`) con procesamiento por lotes (Batch).

Pendiente: pruebas de propiedad opcionales (Hypothesis) de varias secciones, etiquetado real del conjunto de evaluación y ejecución del análisis de inyección. Ver `.kiro/specs/gestor-facturas/tasks.md`.

Nota: con `mcp` 1.9.1 y pydantic 2.14.x la importación de `mcp` puede fallar (`eval_type_backport`). Si ocurre, fije una versión de pydantic compatible.

## Requisitos

- Instalar docker 4.38.0 o superior
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
$env:OCR_MODEL = "gpt-4o"            # opcional; por defecto gpt-4o / claude-sonnet-5-5
$env:DB_PATH = "./data/facturas.db"   # base de datos SQLite
$env:MCP_USER_ID = "usuario_prueba"   # usuario de la sesión
$env:INVOICES_DIR = "./facturas"      # carpeta permitida para imágenes
$env:SQLITE_JOURNAL_MODE = "DELETE"   # modo de journal de SQLite (ver nota)
```

Nota sobre `SQLITE_JOURNAL_MODE`: si no se define, SQLite usa `WAL`, que crea los archivos auxiliares `facturas.db-wal` y `facturas.db-shm`. El modo queda guardado en el propio archivo de la base. WAL no funciona sobre el volumen `./data` de Docker Desktop en Windows y macOS (`sqlite3.OperationalError: disk I/O error`), por eso el compose usa `DELETE`. Si comparte `./data/facturas.db` entre la ejecución local y Docker, use también `DELETE` en local. Si no, la base vuelve a WAL y el contenedor deja de abrirla. Valores admitidos: `WAL`, `DELETE`, `TRUNCATE`, `PERSIST`, `MEMORY`; cualquier otro valor se trata como `WAL`.

Estas líneas `$env:` solo aplican a la sesión actual de PowerShell. No las copie al archivo `.env`, que usa otro formato (ver sección 6).

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
python -m agent.main .\facturas\batch1-0059.jpg
```

Los prompts de confirmación se muestran en pantalla y las respuestas se leen del teclado. Al final se imprime el resultado y la razón de parada. Las trazas se guardan en `traces/`.

Si se ejecuta sin ruta (`python -m agent.main`), el agente la pide por teclado cuando hay una terminal interactiva. Si no hay terminal, o si la respuesta queda vacía, imprime el uso con Docker y termina con código 64, sin iniciar los servidores MCP.

Códigos de salida:

| Código | Significado |
|---|---|
| 0 | Éxito. |
| 1 | Error de validación o de arranque. |
| 2 | Cancelado por el usuario. |
| 3 | Límite de pasos o de tokens. |
| 64 | Falta la ruta de la imagen. |

### 6. Docker

```powershell
docker compose up --build
```

Levanta los dos servidores MCP por **Streamable HTTP** y la API de pruebas con Swagger, todo con un solo comando:

| Servicio | URL | Descripción |
|---|---|---|
| `api-pruebas` | `http://127.0.0.1:8000/docs` | Swagger. `/pipeline/run` y `/batch/run` llaman a los MCP por HTTP. |
| `finanzas-mcp` | `http://127.0.0.1:8001/mcp` | MCP de finanzas (`/health` para healthcheck). |
| `ocr-mcp` | `http://127.0.0.1:8002/mcp` | MCP de OCR (`/health` para healthcheck). |

La API arranca cuando ambos MCP están saludables. Se conecta a ellos con `FINANZAS_MCP_URL` y `OCR_MCP_URL` (ya definidas en el compose); si no están definidas, usa los servicios en proceso. El agente CLI usa las mismas variables si se definen; si no, lanza los MCP por stdio.

Los servidores aceptan `--transport stdio|streamable-http`, `--host` y `--port` (o `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`); el valor por defecto es `stdio`.

El compose monta `./data` (base de datos) en `/app/data`, `./facturas` en `/app/facturas` y `./traces` en `/app/traces`. Fija dentro del contenedor `DB_PATH`, `INVOICES_DIR`, `TRACES_DIR` y `SQLITE_JOURNAL_MODE=DELETE`; estos valores prevalecen sobre los del `.env`. Las demás variables (claves del LLM, `LLM_PROVIDER`, `OCR_MODEL`, `MCP_USER_ID`, `API_TEST_MODE`) se leen del archivo `.env`.

El `.env` usa formato dotenv: una variable por línea, `NOMBRE=valor`, sin prefijo `$env:`, sin espacios alrededor de `=` y con los comentarios en líneas propias que empiezan con `#`. Ejemplo:

```dotenv
# Proveedor y clave del LLM
LLM_PROVIDER=openai
OPENAI_API_KEY=tu-clave
MCP_USER_ID=usuario_prueba
SQLITE_JOURNAL_MODE=DELETE
```

Si el `.env` tiene sintaxis de PowerShell, Compose falla con `unexpected character "$" in variable name`.

#### Solución de problemas

Si `http://127.0.0.1:8000/docs` responde `ERR_CONNECTION_REFUSED`, el servicio `api-pruebas` no está corriendo. Revise el estado y los logs:

```powershell
docker compose ps -a
docker compose logs --tail 50 api-pruebas
```

Si `GET /transacciones` (o cualquier acceso a la base) responde `INTERNAL_ERROR` y los logs muestran `disk I/O error`, la base quedó en modo WAL. Detenga los contenedores, cierre cualquier programa que tenga abierta la base y mueva los tres archivos a un respaldo. La base se vuelve a crear vacía al arrancar, así que haga esto solo si la base no tiene datos que necesite:

```powershell
docker compose stop
New-Item -ItemType Directory data\respaldo_wal -Force
Move-Item data\facturas.db* data\respaldo_wal\
docker compose up -d --build
```

Si la base sí tiene datos, conviértala en lugar de moverla: `python -c "import sqlite3; c=sqlite3.connect('data/facturas.db'); print(c.execute('PRAGMA journal_mode=DELETE').fetchone())"`. El comando debe imprimir `('delete',)`.

Agente CLI (perfil `cli`, no arranca con `up`): `docker compose run --rm gestor-facturas python -m agent.main /app/facturas/mi_factura.jpg`.

Cree `.env` con la clave del LLM (y opcionalmente `MCP_USER_ID`, `API_TEST_MODE`) y ponga las imágenes en `facturas/`. Los puertos se publican solo en `127.0.0.1`. Los servicios comparten `./data`, `./facturas` y `./traces`.

## Proveedor de LLM

| Variable | Descripción |
|---|---|
| `LLM_PROVIDER` | `openai` o `anthropic`. Si falta, usa Anthropic solo cuando existe `ANTHROPIC_API_KEY` y no `OPENAI_API_KEY`; si no, OpenAI. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Clave del proveedor elegido. |
| `OCR_MODEL` | Modelo con visión. Por defecto `gpt-4o` (OpenAI) o `claude-sonnet-5-5` (Anthropic). Si el proveedor retira un modelo, la API responde `[OCR_FAILURE] ... (NotFoundError)`; use un modelo vigente. |

## API de pruebas (`api_pruebas`)

Capa HTTP (FastAPI) sobre los mismos servicios de negocio, pensada para probar el pipeline sin usar la CLI. Todas las operaciones se ejecutan con el usuario de `MCP_USER_ID`; ningún request acepta `user_id`.

### Cómo levantarla

Desde esta carpeta (`Backend`):

```powershell
python -m api_pruebas                          # 127.0.0.1:8000 por defecto
python -m api_pruebas --host 127.0.0.1 --port 8000
uvicorn api_pruebas.app:app                    # alternativa directa
```

El host por defecto es `127.0.0.1`. Si se usa otro host, el lanzador imprime una advertencia de red. La documentación interactiva (Swagger) queda en `http://127.0.0.1:8000/docs`.

### Variables de entorno

| Variable | Descripción |
|---|---|
| `MCP_USER_ID` | Obligatoria. Usuario con el que se ejecuta todo. Si falta o está vacía, la API no arranca. |
| `DB_PATH` | Base SQLite. Por defecto `./data/facturas.db`. |
| `SQLITE_JOURNAL_MODE` | Modo de journal de SQLite. Por defecto `WAL`; use `DELETE` si comparte la base con Docker. |
| `INVOICES_DIR` | Carpeta permitida para imágenes. Por defecto `./facturas`. |
| `TRACES_DIR` | Carpeta de trazas. Por defecto `traces`. |
| `API_TEST_MODE` | `true` habilita `/test/*` y `auto_confirmar`. Por defecto apagado. |
| `API_TEST_DB_ALLOWLIST` | Bases o carpetas permitidas para `/test/*`, separadas por `;` o por el separador de rutas del sistema. Si se define, es la única regla. Si no, el nombre del archivo de la base debe contener `test` o `prueba`. |
| `OCR_MODEL` | Modelo con visión para el OCR (ver Proveedor de LLM). |
| `MAX_IMAGE_BYTES` | Tamaño máximo de imagen subida a `/ocr`. Por defecto 10 MiB. |
| `BATCH_MAX_IMAGES` | Máximo de imágenes por Batch, entre 1 y 100. Por defecto 100. |
| `BATCH_TRACES_DIR` | Carpeta de resultados de Batch. Por defecto `<TRACES_DIR>/batch`. |

### Endpoints

| Método y ruta | Función |
|---|---|
| `POST /ocr` | Extrae datos de una imagen subida. El resultado se marca como contenido no confiable. |
| `POST /validar` | Valida los datos de una factura. |
| `GET /transacciones` | Lista las transacciones del usuario. |
| `POST /pipeline/run` | Ejecuta el pipeline sobre una imagen (`ruta`, `respuestas`). |
| `POST /batch/run` | Procesa todas las imágenes de una subcarpeta de `INVOICES_DIR`. |
| `GET /batch` | Lista los Batches del usuario, del más reciente al más antiguo. |
| `GET /batch/{batch_id}` | Reporte de un Batch. |
| `GET /trazas` | Lista las trazas del usuario (incluye las de Batch). |
| `GET /trazas/{trace_id}` | Traza completa, con datos sensibles redactados. |
| `POST /test/reset` | Elimina las transacciones del usuario. Solo modo de pruebas. |
| `POST /test/seed` | Inserta transacciones de prueba. Solo modo de pruebas. |

No existen `/health`, `/config`, `/duplicados` ni `POST /transacciones`. Los endpoints `/test/*` responden 403 si `API_TEST_MODE` no es `true` (`TEST_MODE_DISABLED`) o si la base no está permitida (`TEST_DB_NOT_ALLOWED`).

### Batch

`POST /batch/run` recibe un `BatchIn`:

| Campo | Tipo | Descripción |
|---|---|---|
| `subcarpeta` | texto | Obligatorio. Ruta relativa dentro de `INVOICES_DIR`. Se rechazan rutas absolutas, `..`, unidades, enlaces simbólicos y nombres reservados de Windows. |
| `respuestas_por_defecto` | lista de textos | Respuestas guionadas a los prompts, para toda imagen sin entrada propia. Máximo 50. |
| `respuestas_por_imagen` | objeto | Nombre de imagen a lista de respuestas. Cada clave debe ser una imagen de la subcarpeta. Máximo 100 claves. |
| `auto_confirmar` | booleano | Responde solo los tokens de confirmación cuando se agota el guion. Requiere `API_TEST_MODE=true`; si no, responde 403 `TEST_MODE_DISABLED`. Por defecto `false`. |
| `confirmar_duplicados` | booleano | Con `auto_confirmar`, responde `si` a la confirmación de posibles duplicados. Por defecto `false`. |

Solo se procesan las imágenes directas de la subcarpeta (sin recursión), en orden alfabético. Cada imagen recibe una clasificación:

| Clasificación | Significado |
|---|---|
| `ok` | Registrada. |
| `duplicada` | Coincide con una transacción existente (`DUPLICATE_DB`) o con una imagen anterior del mismo Batch (`DUPLICATE_IN_BATCH`, con `duplicada_de`). |
| `no_valida` | Falló la validación (con `reglas_incumplidas`) o la ruta o imagen no es válida. |
| `step_limit` | Se alcanzó el límite de pasos. |
| `token_limit` | Se alcanzó el límite de tokens. |
| `user_rejection` | No hubo confirmación del usuario. |
| `error` | Falla de una herramienta o error inesperado. |

Una imagen con error no detiene el Batch. Los errores de entrada (`BATCH_PATH_VIOLATION`, `BATCH_FOLDER_NOT_FOUND`, `BATCH_NO_IMAGES`, `BATCH_TOO_MANY_IMAGES`, `BATCH_UNKNOWN_IMAGE`) se detectan antes de procesar nada.

Ejemplos con las facturas de `facturas/test_batch_1`:

```bash
# Con auto_confirmar (requiere API_TEST_MODE=true)
curl -X POST http://127.0.0.1:8000/batch/run \
  -H "Content-Type: application/json" \
  -d '{"subcarpeta": "test_batch_1"}'

curl http://127.0.0.1:8000/batch
curl http://127.0.0.1:8000/batch/<batch_id>
```

Sin `auto_confirmar` ni respuestas guionadas, el pipeline no recibe confirmación y las imágenes válidas terminan como `user_rejection`. Para registrar, agregue `"auto_confirmar": true` o envíe `respuestas_por_defecto`.

Ubicación de resultados: `traces/batch/<batch_id>/summary.json` (reporte del Batch) y una traza JSON por imagen en la misma carpeta. Las trazas también se consultan con `GET /trazas` y `GET /trazas/{trace_id}`.

Limitaciones conocidas:

- Un Batch interrumpido (por ejemplo, al caer el proceso) puede quedar sin `summary.json`. En ese caso no aparece en `GET /batch` ni en `GET /batch/{batch_id}`, aunque sus trazas existan.
- Los Batches concurrentes comparten la misma base SQLite, por lo que la detección de duplicados entre ellos depende del orden de ejecución.
