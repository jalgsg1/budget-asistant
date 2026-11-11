# Implementation Plan: API de pruebas (api-pruebas-endpoints)

## Overview

El diseño usa Python (FastAPI, pydantic, Hypothesis), igual que el resto de `Backend/`, así que todas las tareas se implementan en Python. El orden es: refactor mínimo de código existente, dependencias, paquete `api_pruebas` (configuración interna, errores, esquemas, servicios, Pipeline), módulo de Batch (selección, auto-confirmación, clasificación, reporte, extensión de trazas), routers y aplicación, y README.

Endpoints que se implementan: `POST /ocr`, `POST /validar`, `GET /transacciones`, `POST /pipeline/run`, `POST /batch/run`, `GET /batch`, `GET /batch/{batch_id}`, `GET /trazas`, `GET /trazas/{trace_id}`, `POST /test/reset`, `POST /test/seed`, más `/docs` y `/openapi.json`. No hay endpoints `/health`, `/config`, `/duplicados` ni `POST /transacciones`; `buscar_duplicados` y `registrar_transaccion` existen solo como métodos internos de `ServiciosNegocio` y herramientas del Pipeline.

Reglas generales para todas las tareas:

- Las pruebas nuevas van en `Backend/tests/` como `test_api_*.py`, compatibles con `unittest` (clases `unittest.TestCase`, descubribles con `python -m unittest discover -s tests`). Las pruebas de propiedades usan `@given` de Hypothesis dentro de `TestCase`, con `@settings(max_examples=100)` como mínimo y el comentario `Feature: api-pruebas-endpoints, Property N: <texto>`. Cada prueba de propiedad va en su propio archivo `tests/test_api_prop_<nn>.py` (por ejemplo `test_api_prop_11.py`) para evitar conflictos entre tareas paralelas.
- La API nunca importa `mcp`, `finanzas_mcp.server` ni `ocr_mcp.server`.
- Las pruebas nunca llaman a un proveedor OCR real: se inyecta un `extractor_ocr` falso.
- Las pruebas de Batch usan `BATCH_MAX_IMAGES` bajo (por ejemplo 3) para el límite; los symlinks se crean con `os.symlink` y la prueba se salta con `self.skipTest` si el sistema no lo permite.
- Las 63 pruebas existentes deben seguir pasando después de cada checkpoint (requisito 9.5).

## Tasks

- [x] 1. Refactor mínimo de código existente (sin cambiar comportamiento)
  - [x] 1.1 Crear `ocr_mcp/ocr_core.py` y reutilizarlo desde `ocr_mcp/server.py`
    - Mover tal cual `ALLOWED_EXTENSIONS`, `OcrToolError`, `validar_ruta(ruta, invoices_dir=None, max_bytes=None)` y `wrap_untrusted` desde `ocr_mcp/server.py`, sin importar `mcp`
    - Leer los valores por defecto de `INVOICES_DIR` y `MAX_IMAGE_BYTES` del entorno con los mismos defaults (`./facturas`, 10 MB)
    - En `ocr_mcp/server.py` reemplazar las definiciones por `from ocr_mcp.ocr_core import ...` conservando los nombres públicos
    - _Requirements: 1.1, 1.3, 5.5, 9.5_

  - [x] 1.2 Crear `finanzas_mcp/business/factura.py` con `evaluar_factura` y delegar desde `finanzas_mcp/server.py`
    - Implementar `evaluar_factura(datos) -> ResultadoFactura` aplicando R1, R2, R3, R4 y R6 en el mismo orden y con las mismas condiciones que `_handle_validar_factura`, conservando todas las reglas fallidas (regla, `valid`, `code`, `message`)
    - Hacer que `_handle_validar_factura` use esta función y mantenga su salida (`is_valid` o `ValidationError` con el primer código)
    - No importar `mcp` en `factura.py`
    - _Requirements: 2.1, 2.5, 9.5_

  - [x] 1.3 Agregar `TransactionRepository.eliminar_por_usuario(user_id) -> int`
    - Ejecutar `DELETE FROM transactions WHERE user_id = ?`, hacer commit y devolver el número de filas eliminadas
    - No modificar ningún método existente
    - _Requirements: 7.2, 9.5_

  - [ ]* 1.4 Escribir pruebas unittest del refactor en `tests/test_api_refactor.py`
    - Paridad: `evaluar_factura` frente a las salidas esperadas de `_handle_validar_factura` para los casos de `tests/test_reglas_r1_r4.py`
    - `validar_ruta` en `ocr_core` (traversal, extensión no permitida, archivo inexistente, tamaño máximo)
    - `eliminar_por_usuario` borra solo las filas del usuario indicado y devuelve el conteo
    - _Requirements: 1.3, 2.5, 7.2, 9.5_

- [x] 2. Checkpoint - Verificar el refactor
  - Ejecutar la suite existente (63 pruebas) y las pruebas de la tarea 1; asegurar que todas pasan, preguntar al usuario si surgen dudas.

- [x] 3. Dependencias de la API
  - [x] 3.1 Instalar y fijar `fastapi`, `uvicorn` y `python-multipart` en `requirements.txt`
    - Instalar en `.venv` una versión de `fastapi` compatible con `starlette 1.10.0` y `pydantic 2.14.3` (o ajustar a la versión que resulte compatible), y verificar con `pip check` y con `python -c "from fastapi.testclient import TestClient"` (usa `httpx 0.28.1`)
    - Agregar las tres líneas con `==` (versiones realmente instaladas y probadas) sin alterar las líneas existentes
    - Confirmar que la suite existente sigue pasando con las nuevas versiones instaladas
    - _Requirements: 9.4, 9.5_

  - [ ]* 3.2 Escribir prueba de humo de `requirements.txt` en `tests/test_api_requirements.py`
    - Comprobar que las líneas de `fastapi`, `uvicorn` y `python-multipart` usan `==`
    - _Requirements: 9.4_

- [x] 4. Paquete `api_pruebas`: configuración interna, errores y esquemas
  - [x] 4.1 Crear `api_pruebas/__init__.py` y `api_pruebas/config.py`
    - Módulo de configuración interno mínimo, sin endpoint: `Config` (dataclass inmutable), `ConfigError` y `cargar_config(env=os.environ)`
    - Cargar con `python-dotenv` (`load_dotenv` sin `override`: primero `Backend/.env`, luego `budget-asistant/.env`), de modo que el entorno del proceso prevalece
    - `MCP_USER_ID` ausente, vacío o con solo espacios lanza `ConfigError` con el nombre de la variable
    - Defaults `DB_PATH=./data/facturas.db` e `INVOICES_DIR=./facturas` resueltos contra `Backend/`; leer `API_TEST_MODE` (solo `true`, sin distinguir mayúsculas), `API_TEST_DB_ALLOWLIST`, `TRACES_DIR`, `OCR_MODEL`, `MAX_IMAGE_BYTES` y la política con `load_policy` (más el JSON crudo `policy_dict`)
    - Agregar `BATCH_TRACES_DIR` (campo `batch_traces_dir`, default `<traces_dir>/batch`, relativa se resuelve contra `Backend/`) y `BATCH_MAX_IMAGES` (campo `batch_max_images`, default 100); un valor que no sea entero entre 1 y 100 lanza `ConfigError` con el nombre de la variable
    - Nunca guardar ni serializar valores de claves de API
    - _Requirements: 4.5, 5.6, 5.11, 7.1, 7.5_

  - [x] 4.2 Crear `api_pruebas/errores.py`
    - Implementar `ErrorApi` (status, code, message), `ErrorEstandar` y la tabla única de mapeo excepción a `(http_status, code, message)` del diseño (`ValidationError`, `FilterError`, `DateRangeError`, `OcrToolError`, `ToolError`, subida, trazas, modo pruebas)
    - Agregar los códigos de Batch: `BATCH_PATH_VIOLATION` (400), `BATCH_FOLDER_NOT_FOUND` (404), `BATCH_NO_IMAGES` (400), `BATCH_TOO_MANY_IMAGES` (400), `BATCH_UNKNOWN_IMAGE` (400), `INVALID_BATCH_ID` (400), `BATCH_NOT_FOUND` (404) y `TEST_MODE_DISABLED` (403) para la auto-confirmación
    - Implementar `redactar(obj)` recursivo (valores de variables `*_API_KEY` de 8 o más caracteres y patrón `sk-[A-Za-z0-9_-]{16,}`) y un `logging.Filter` para el logger `api_pruebas`
    - Implementar los handlers para `ErrorApi`, errores de negocio, `RequestValidationError` (mensaje con `loc` y `msg`, sin eco del valor), `HTTPException` y `Exception` (500 con mensaje fijo `INTERNAL_ERROR` y sin pila) y una función `registrar_handlers(app)`
    - _Requirements: 1.3, 1.6, 3.3, 3.4, 5.2, 5.3, 5.4, 5.6, 5.9, 5.22, 5.23, 6.5, 10.1, 10.2_

  - [ ]* 4.3 Escribir prueba de propiedad para redacción de secretos
    - **Property 1: Redacción de secretos**
    - **Validates: Requirements 1.6, 5.24, 6.5, 10.2**

  - [ ]* 4.4 Escribir prueba de propiedad para el mapeo de errores
    - **Property 22: El mapeo de errores conserva el código**
    - **Validates: Requirements 10.1, 10.3**

  - [x] 4.5 Crear `api_pruebas/esquemas.py`
    - Definir `ModeloEstricto` (`extra="forbid"`, `allow_inf_nan=False`) y los modelos de request: `FacturaIn`, `PipelineIn`, `SeedItem`, `SeedIn`
    - Definir `BatchIn` (`subcarpeta`, `respuestas_por_defecto`, `respuestas_por_imagen`, `auto_confirmar`, `confirmar_duplicados`) con límites de tamaño: máximo 100 claves en `respuestas_por_imagen` y 50 respuestas por lista (422 si se superan)
    - Definir los modelos de response: `ErrorEstandar`, `ReglaResultado`, `ValidacionRespuesta`, `OcrRespuesta` (con `untrusted_content` e `is_untrusted` como `Literal[True]`), `TransaccionOut`, `PipelineRespuesta`, `TrazaResumen`, `ResetRespuesta`, `SeedRespuesta`
    - Definir los modelos de Batch: `Clasificacion` (Literal de los siete valores), `ImagenResultado`, `ConteoClasificaciones`, `ReporteBatch` (sin exponer `user_id`), `BatchResumen` y `BatchRespuesta`
    - _Requirements: 2.4, 5.1, 5.7, 5.18, 5.20, 7.3, 8.3_

  - [ ]* 4.6 Escribir pruebas unittest de configuración y esquemas en `tests/test_api_config_esquemas.py`
    - `cargar_config` lanza `ConfigError` si falta `MCP_USER_ID`; `BATCH_MAX_IMAGES` por defecto es 100 y valores como `0`, `101` o `abc` lanzan `ConfigError`; `BATCH_TRACES_DIR` por defecto es `<traces_dir>/batch`
    - `BatchIn` rechaza campos desconocidos y listas que superan los límites; `ReporteBatch` no contiene `user_id`
    - _Requirements: 5.1, 5.6, 5.18_

- [x] 5. Servicios de negocio y módulos de apoyo
  - [x] 5.1 Crear `api_pruebas/servicios.py` con `ServiciosNegocio`
    - Métodos `validar`, `listar`, `ocr_ruta`, `ocr_subida`, `reset`, `seed`, y los internos sin endpoint `duplicados` y `registrar` (solo para el adaptador de herramientas del Pipeline); ninguno acepta `user_id` y todos usan `config.user_id`
    - Un `TransactionRepository` por operación (`with`), pasando `policy_dict` a listar y registrar; quitar `confirmation_token`, `high_amount_token` y `user_id` del payload antes de `registrar_transaccion`
    - `listar` devuelve todas las filas del usuario que cumplen los filtros (sin límite inventado); un `ValidationError` de fecha en filtros se trata como 400 `INVALID_DATE_FORMAT`
    - `ocr_ruta`: `ocr_core.validar_ruta` antes de leer, extractor inyectable, resultado con `wrap_untrusted` e `is_untrusted=True`; excepciones del extractor a `OcrToolError("OCR_FAILURE")` con solo el nombre del tipo y mensaje redactado
    - `ocr_subida`: validar extensión (415), firma de bytes (415) y tamaño con lectura limitada a `max+1` (413) antes de escribir; guardar como `<uuid4>.<ext>` en `invoices_dir`
    - `obtener_extractor_ocr()` con import diferido de `OcrClient` y `threading.Lock`
    - `seed`: validar todos los elementos con `evaluar_factura` antes de insertar; si alguno falla, 422 y no insertar ninguno
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 7.2, 7.3, 7.4_

  - [x] 5.2 Crear `api_pruebas/trazas.py` (trazas en el directorio principal)
    - `listar_trazas(traces_dir, user_id)`: ignorar archivos ilegibles o sin `trace_id`, filtrar por `user_id`, ordenar por `created_at` descendente
    - `leer_traza(traces_dir, user_id, trace_id)`: validar `^[A-Za-z0-9-]{1,64}$` antes de tocar el disco (`INVALID_TRACE_ID`), buscar por nombre `*_{trace_id[:8]}.json`, comprobar `trace_id` y `user_id` en el JSON, mismo `TRACE_NOT_FOUND` si no existe o es de otro usuario, devolver el contenido con `redactar`
    - Permitir inyectar el lector de directorio para pruebas
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 5.3 Crear `api_pruebas/modo_pruebas.py`
    - Implementar `db_es_de_pruebas(db_path, allowlist)` (lista explícita o nombre de archivo con `test`/`prueba`, rutas con `Path.resolve()`)
    - Implementar la comprobación de permisos en orden (primero `TEST_MODE_DISABLED`, luego `TEST_DB_NOT_ALLOWED`) y el conjunto de ejemplo de 5 transacciones válidas (CRC y USD, categorías de `CLOSED_CATEGORY_LIST`)
    - _Requirements: 7.1, 7.4, 7.5_

  - [ ]* 5.4 Escribir prueba de propiedad para el permiso de reset y seed
    - **Property 20: Permiso de reset y seed**
    - **Validates: Requirements 7.1, 7.5**

  - [ ]* 5.5 Escribir pruebas unittest de `ServiciosNegocio` en `tests/test_api_servicios.py`
    - Subida con firma incorrecta (415), exceso de tamaño (413), nombre con traversal (se descarta), carpeta sin cambios tras rechazo
    - Extractor que lanza: `OCR_FAILURE` sin la clave en el mensaje
    - El conjunto de ejemplo de `modo_pruebas` es válido según `evaluar_factura`
    - _Requirements: 1.4, 1.6, 7.4_

- [x] 6. Adaptador de herramientas y ejecución del Pipeline
  - [x] 6.1 Crear `api_pruebas/herramientas.py`
    - `construir_tools(servicios)` con las cinco claves de `TOOL_SERVERS` (`ocr_imagen`, `validar_factura`, `buscar_duplicados`, `listar_transacciones`, `registrar_transaccion`) y el mismo contrato que `McpToolbox.tools`; `buscar_duplicados` y `registrar_transaccion` usan los métodos internos de `ServiciosNegocio` y no tienen ruta HTTP
    - `ocr_imagen` devuelve `wrap_untrusted(result)` como JSON `str`; `validar_factura` devuelve `{"is_valid": True, "errors": []}` o lanza `ToolError(primer_codigo, mensaje)`; `registrar_transaccion` ignora `user_id` del payload y devuelve `{"id", "status": "registrada"}`
    - Convertir excepciones de negocio en `ToolError` con el mismo código
    - _Requirements: 4.1, 4.6, 10.3_

  - [x] 6.2 Crear `api_pruebas/pipeline_runner.py`
    - `ScriptedIO` (implementa `UserIO`): `ask` entrega `respuestas[i]` o `None` al agotarse y registra `prompts`; `notify` acumula en `mensajes`
    - `ejecutar_pipeline(servicios, config, ruta, respuestas)`: validar la ruta con `ocr_core.validar_ruta` antes de crear el Pipeline; crear por solicitud `ScriptedIO`, `tools` e `InvoicePipeline(tools, io, config.policy, config.user_id, str(config.traces_dir))`; capturar `ToolError` que escape de `run` y mapearlo (400 o 502); devolver `PipelineRespuesta` para cualquier `status`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 4.8_

  - [ ]* 6.3 Escribir prueba de propiedad para `ScriptedIO`
    - **Property 8: ScriptedIO entrega las respuestas en orden**
    - **Validates: Requirements 4.1, 4.3**

  - [ ]* 6.4 Escribir pruebas unittest de `construir_tools` en `tests/test_api_herramientas.py`
    - Las cinco claves existen; los errores de negocio se convierten en `ToolError` con el mismo código; `registrar_transaccion` ignora `user_id` del payload
    - _Requirements: 4.6, 10.3_

- [x] 7. Checkpoint - Verificar el núcleo de la API
  - Ejecutar la suite completa (las 63 pruebas existentes y las nuevas); asegurar que todas pasan, preguntar al usuario si surgen dudas.

- [x] 8. Módulo de Batch (`api_pruebas/batch.py`) y extensión de trazas
  - [x] 8.1 Implementar en `api_pruebas/batch.py` la resolución de subcarpeta y la selección de imágenes
    - `resolver_subcarpeta(subcarpeta, invoices_dir)`: rechazar vacía, con NUL, absoluta (`Path`, `PureWindowsPath`, `PurePosixPath`), unidad, UNC, segmentos `..` o `.`, `:` en un segmento y nombres reservados de Windows; recorrer los componentes rechazando symlinks; exigir destino contenido en `invoices_dir.resolve()` y distinto de él; lanzar `BATCH_PATH_VIOLATION` (400) o `BATCH_FOLDER_NOT_FOUND` (404) si no existe o no es directorio
    - `seleccionar_imagenes(carpeta, max_images)`: solo hijos directos, archivos regulares que no sean symlink, extensión (sin distinguir mayúsculas) en `ALLOWED_EXTENSIONS`, orden `sorted(key=lambda p: (p.name.casefold(), p.name))`; lanzar `BATCH_NO_IMAGES` si no hay y `BATCH_TOO_MANY_IMAGES` si supera `batch_max_images`
    - Validar que las claves de `respuestas_por_imagen` estén en la selección (`BATCH_UNKNOWN_IMAGE`)
    - Todas las validaciones ocurren antes de crear el directorio de salida o ejecutar el Pipeline; permitir inyectar el lector de directorio para pruebas
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 8.2 Implementar `AutoConfirmIO` en `api_pruebas/batch.py`
    - Implementa `UserIO` envolviendo a `ScriptedIO`; se construye por imagen con `respuestas_por_imagen[archivo]` (aunque sea lista vacía) o `respuestas_por_defecto`
    - Constantes `TEST-CONFIRM` y `TEST-HIGH-AMOUNT`; reconocer prompts por texto (`token de confirmación para registrar`, `token de confirmación de monto alto`, prefijo `Posibles duplicados`); con el guion agotado y `auto_confirmar` falso devolver `None`; con `auto_confirmar` verdadero responder el token que corresponda, `si` a duplicados solo con `confirmar_duplicados=true` y `None` en cualquier otro prompt
    - Las respuestas provistas explícitamente tienen prioridad; acumular `mensajes` y `prompts`
    - Función de preparación que lanza 403 `TEST_MODE_DISABLED` si `auto_confirmar` es verdadero y `Config.test_mode` es falso, antes de crear ningún `AutoConfirmIO`
    - _Requirements: 5.7, 5.8, 5.9, 5.10_

  - [x] 8.3 Implementar `clasificar` y `clasificar_excepcion` en `api_pruebas/batch.py`
    - Funciones puras que aplican la tabla de reglas del diseño en orden (excepciones, `success`, `step_limit`, `token_limit`, duplicada por entrada de traza `duplicate_confirmation` o por clave `(comercio.strip().casefold(), fecha, round(float(total), 2))` en `vistos`, `no_valida`, `user_rejection`, `error` por defecto) con `motivo` no vacío
    - `no_valida` incluye `reglas_incumplidas` (códigos `error <CODIGO>` de entradas `validar_factura`, únicos y en orden); `duplicada` incluye `duplicada_de` cuando exista coincidencia en `vistos`; `detalle` es una cadena fija corta o el nombre del tipo de excepción, sin pila ni texto del OCR ni claves de API
    - Registrar en `vistos` la clave de toda imagen con los tres campos tras clasificarla
    - _Requirements: 5.13, 5.14, 5.15, 5.16, 5.17, 5.19_

  - [x] 8.4 Implementar `ejecutar_batch`, el reporte y la consulta de reportes en `api_pruebas/batch.py`
    - `ejecutar_batch(servicios, config, req)`: validar modo, subcarpeta, selección y claves; generar `batch_id` uuid4; crear `<batch_traces_dir>/<batch_id>` con `exist_ok=False`; por cada imagen en orden crear un `InvoicePipeline` nuevo con `construir_tools(servicios)`, un `AutoConfirmIO` propio y `traces_dir` del Batch, ejecutar con la ruta relativa a `INVOICES_DIR`, capturar `Exception` por imagen (clasificar `error` y continuar) y clasificar
    - Armar `ReporteBatch` (batch_id, subcarpeta, fecha ISO 8601 UTC, total, conteos, imágenes) aplicando `redactar`; guardar `summary.json` con `user_id` mediante escritura atómica (temporal `summary.json.tmp-<uuid4>`, `flush`, `os.fsync`, `os.replace`; borrar el temporal y responder 500 `INTERNAL_ERROR` si falla)
    - `listar_batches(config)`: hijos directos con nombre `^[A-Za-z0-9-]{1,64}$`, sin symlinks, con `summary.json` legible y `user_id` de la sesión; ordenar por `fecha` descendente
    - `leer_batch(config, batch_id)`: validar el id antes de tocar el disco (`INVALID_BATCH_ID`), comparar contra el listado del directorio, mismo `BATCH_NOT_FOUND` para inexistente, sin resumen o de otro usuario, y devolver el reporte redactado sin `user_id`
    - Sin estado compartido entre Batches (cada uno tiene su `vistos`, contadores y trazas)
    - _Requirements: 5.1, 5.11, 5.12, 5.18, 5.19, 5.20, 5.21, 5.22, 5.23, 5.24, 5.25, 5.26_

  - [x] 8.5 Extender `api_pruebas/trazas.py` para localizar trazas en `traces/batch/<batch_id>/`
    - `listar_trazas(traces_dir, batch_traces_dir, user_id)` y `leer_traza(traces_dir, batch_traces_dir, user_id, trace_id)` recorren `traces_dir` y cada directorio hijo de `batch_traces_dir` (nombre `^[A-Za-z0-9-]{1,64}$`, no symlink, `resolve()` dentro de `batch_traces_dir.resolve()`, un solo nivel sin recursión)
    - Excluir `summary.json` e ignorar archivos que sean symlinks; mantener las mismas restricciones de usuario, de identificador y de redacción
    - Actualizar las llamadas existentes a la nueva firma
    - _Requirements: 5.27, 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ]* 8.6 Escribir prueba de propiedad para la selección de imágenes
    - **Property 13: Selección de imágenes y orden determinista**
    - **Validates: Requirements 5.4, 5.5, 5.6**

  - [ ]* 8.7 Escribir prueba de propiedad para el confinamiento de la subcarpeta
    - **Property 14: Confinamiento de la subcarpeta del Batch**
    - **Validates: Requirements 5.2, 5.3, 5.4**

  - [ ]* 8.8 Escribir prueba de propiedad para la clasificación
    - **Property 11: Clasificación exclusiva y total**
    - **Validates: Requirements 5.13, 5.14, 5.15, 5.16, 5.17, 5.19**

  - [ ]* 8.9 Escribir prueba de propiedad para la consulta de trazas
    - **Property 19: Consulta de trazas segura y aislada**
    - **Validates: Requirements 5.27, 6.1, 6.2, 6.3, 6.4**

  - [ ]* 8.10 Escribir pruebas unittest del módulo batch en `tests/test_api_batch.py`
    - Ejemplos de `AutoConfirmIO` (guion por imagen frente al por defecto, lista vacía explícita, guion agotado sin auto-confirmación)
    - Escritura atómica de `summary.json` (sin temporales residuales; fallo simulado de `os.replace` borra el temporal) y que un directorio sin `summary.json` no aparece en `GET /batch`
    - El valor por defecto de `batch_max_images` es 100
    - _Requirements: 5.7, 5.10, 5.12, 5.20_

  - [ ]* 8.11 Escribir la prueba de contrato de `AutoConfirmIO` contra el Pipeline real en `tests/test_api_batch_contrato.py`
    - Ejecutar `InvoicePipeline` real con OCR simulado y base temporal y comprobar que los textos `Posibles duplicados`, `token de confirmación para registrar` y `token de confirmación de monto alto` siguen disparando las respuestas esperadas de `AutoConfirmIO` (`si` con `confirmar_duplicados`, `TEST-CONFIRM`, `TEST-HIGH-AMOUNT`)
    - Fallar con un mensaje claro si algún texto de prompt cambia en `agent/agent.py`
    - _Requirements: 5.7, 5.8, 5.10_

- [x] 9. Checkpoint - Verificar el módulo de Batch
  - Ejecutar la suite completa (las 63 pruebas existentes y las nuevas); asegurar que todas pasan, preguntar al usuario si surgen dudas.

- [x] 10. Routers FastAPI, aplicación y lanzador
  - [x] 10.1 Crear `api_pruebas/rutas/__init__.py`, `rutas/ocr.py` y `rutas/factura.py`
    - `POST /ocr` multipart con exactamente uno de `ruta` o `archivo` (422 en otro caso) y `POST /validar` (devuelve `reglas` y `valid`); endpoints `def` con `summary`, `response_model` y `responses={...}`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 8.2_

  - [x] 10.2 Crear `rutas/transacciones.py`
    - `GET /transacciones` declara los cinco filtros pero reenvía todas las claves de `request.query_params` a `listar`; `ValidationError` de fecha del listado se mapea a 400 `INVALID_DATE_FORMAT`
    - No se define `POST /transacciones`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 8.2_

  - [x] 10.3 Crear `rutas/pipeline.py`, `rutas/trazas.py` y `rutas/pruebas.py`
    - `POST /pipeline/run`, `GET /trazas`, `GET /trazas/{trace_id}` (usando la firma extendida con `batch_traces_dir`), `POST /test/reset` y `POST /test/seed` (cuerpo opcional; sin cuerpo usa el conjunto de ejemplo), con los controles de `modo_pruebas` antes de abrir la base
    - _Requirements: 4.1, 4.2, 4.4, 5.27, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 8.2_

  - [x] 10.4 Crear `rutas/batch.py`
    - `POST /batch/run` (`BatchIn` a `BatchRespuesta`, errores 400, 403, 404, 422), `GET /batch` (`list[BatchResumen]`) y `GET /batch/{batch_id}` (`ReporteBatch`, errores 400 y 404); endpoints `def` con `summary`, `response_model` y `responses={...}` que documentan los códigos `BATCH_*`
    - Delegar en `ejecutar_batch`, `listar_batches` y `leer_batch`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 5.9, 5.20, 5.21, 5.22, 5.23, 8.2, 8.3_

  - [x] 10.5 Crear `api_pruebas/app.py` y `api_pruebas/__main__.py`
    - `crear_app(config=None, extractor_ocr=None)` y `app`; `lifespan` que carga la configuración (termina con `ConfigError` si falta `MCP_USER_ID`), guarda `app.state.config` y `app.state.servicios`; registrar handlers y todos los routers (`ocr`, `factura`, `transacciones`, `pipeline`, `batch`, `trazas`, `pruebas`; sin routers de salud ni config); documentación en `/docs` y `/openapi.json`
    - `host_es_local(host)` (verdadero solo para `127.0.0.1` y `localhost`) y advertencia de exposición en red en el lanzador y en el `lifespan` (best-effort con `--host` o `API_HOST`)
    - `python -m api_pruebas [--host 127.0.0.1] [--port 8000]` con `uvicorn.run("api_pruebas.app:app", ...)`; host por defecto `127.0.0.1`
    - Verificar que `import api_pruebas.app` no importa `mcp`
    - _Requirements: 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.5, 10.1, 10.2_

  - [ ]* 10.6 Escribir prueba de propiedad para la advertencia de exposición
    - **Property 23: Advertencia de exposición en red**
    - **Validates: Requirements 9.3**

  - [ ]* 10.7 Escribir prueba de propiedad para el confinamiento de rutas
    - **Property 2: Confinamiento de rutas**
    - **Validates: Requirements 1.1, 1.3, 4.4**

  - [ ]* 10.8 Escribir prueba de propiedad para subidas confinadas y acotadas
    - **Property 3: Subidas confinadas y acotadas**
    - **Validates: Requirements 1.2, 1.4**

  - [ ]* 10.9 Escribir prueba de propiedad para el resultado OCR no confiable
    - **Property 4: El resultado OCR siempre es no confiable**
    - **Validates: Requirements 1.5, 1.7**

  - [ ]* 10.10 Escribir prueba de propiedad para validación coherente con las reglas
    - **Property 5: La validación es coherente con las reglas**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5**

  - [ ]* 10.11 Escribir prueba de propiedad para campos desconocidos y `user_id`
    - **Property 6: Campos desconocidos y `user_id` se rechazan sin efectos**
    - **Validates: Requirements 2.4**

  - [ ]* 10.12 Escribir prueba de propiedad para el listado filtrado
    - **Property 7: Listado filtrado, acotado en rango y aislado**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

  - [ ]* 10.13 Escribir prueba de propiedad para el Pipeline por HTTP
    - **Property 9: El Pipeline reporta cualquier resultado con 200 y usa los mismos servicios**
    - **Validates: Requirements 4.2, 4.5, 4.6, 4.7**

  - [ ]* 10.14 Escribir prueba de propiedad para ejecuciones concurrentes
    - **Property 10: Ejecuciones concurrentes del Pipeline son independientes**
    - **Validates: Requirements 4.8**

  - [ ]* 10.15 Escribir prueba de propiedad para reset y seed
    - **Property 21: Reset y seed afectan solo al Usuario_Sesion**
    - **Validates: Requirements 7.2, 7.3, 7.6**

  - [ ]* 10.16 Escribir prueba de propiedad para conteos y reporte del Batch
    - **Property 12: Los conteos del reporte suman el total**
    - **Validates: Requirements 5.1, 5.11, 5.12, 5.18**

  - [ ]* 10.17 Escribir prueba de propiedad para la auto-confirmación
    - **Property 15: La auto-confirmación solo existe con Modo_Pruebas**
    - **Validates: Requirements 5.7, 5.8, 5.9, 5.10**

  - [ ]* 10.18 Escribir prueba de propiedad para fallos por imagen
    - **Property 16: Un fallo en una imagen no detiene el Batch**
    - **Validates: Requirements 5.19, 5.24**

  - [ ]* 10.19 Escribir prueba de propiedad para Batches concurrentes
    - **Property 17: Batches concurrentes son independientes**
    - **Validates: Requirements 5.26**

  - [ ]* 10.20 Escribir prueba de propiedad para la consulta de reportes de Batch
    - **Property 18: Consulta de reportes de Batch segura y aislada**
    - **Validates: Requirements 5.20, 5.21, 5.22, 5.23, 5.24, 5.25**

  - [ ]* 10.21 Escribir pruebas de ejemplo y de humo en `tests/test_api_humo.py`
    - `POST /ocr` con extractor que lanza (502 sin la clave); endpoint con excepción no controlada (500 sin pila); seed sin cuerpo; `POST /pipeline/run` con ruta fuera de `INVOICES_DIR` (400 y herramientas sin invocar)
    - `/openapi.json` incluye `/batch/run`, `/batch` y `/batch/{batch_id}` y no contiene `/health`, `/config`, `/duplicados` ni `POST /transacciones`
    - OpenAPI: `/docs` y `/openapi.json` responden y cada operación tiene `summary`, `responses` y `response_model`
    - Importación de `api_pruebas.app` en un subproceso con `sys.modules['mcp'] = None`: no falla y `mcp` no queda cargado
    - _Requirements: 1.6, 4.4, 7.4, 8.1, 8.2, 8.3, 9.5, 10.2_

  - [ ]* 10.22 Escribir pruebas de ejemplo HTTP del Batch en `tests/test_api_batch_http.py`
    - `POST /batch/run` sobre una subcarpeta de prueba con OCR simulado: 200, `batch_id`, `summary.json` y trazas en `traces/batch/<batch_id>/`
    - Errores: subcarpeta absoluta o con `..` (400), inexistente (404), sin imágenes (400), exceso de `BATCH_MAX_IMAGES` (400), `auto_confirmar` con Modo_Pruebas apagado (403), claves de `respuestas_por_imagen` desconocidas (400); ningún caso crea directorio de salida
    - `GET /batch`, `GET /batch/{batch_id}` (400 con id inválido, 404 inexistente) y `GET /trazas/{trace_id}` para una traza de Batch
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 5.9, 5.11, 5.12, 5.20, 5.21, 5.22, 5.23, 5.27_

- [x] 11. Checkpoint - Verificar la API completa
  - Ejecutar la suite completa (las 63 pruebas existentes y las nuevas); asegurar que todas pasan, preguntar al usuario si surgen dudas.

- [x] 12. Documentación
  - [x] 12.1 Actualizar `Backend/README.md`
    - Sección de la API de pruebas con solo los endpoints que existen: `POST /ocr`, `POST /validar`, `GET /transacciones`, `POST /pipeline/run`, `POST /batch/run`, `GET /batch`, `GET /batch/{batch_id}`, `GET /trazas`, `GET /trazas/{trace_id}`, `POST /test/reset`, `POST /test/seed`; indicar que no hay `/health`, `/config`, `/duplicados` ni `POST /transacciones`
    - Subsección de Batch: cuerpo de `BatchIn`, clasificaciones, `auto_confirmar` (solo con `API_TEST_MODE=true`) y `confirmar_duplicados`, variables `BATCH_MAX_IMAGES` y `BATCH_TRACES_DIR`, y ejemplos `curl` con la subcarpeta `facturas/test_batch_1` (`POST /batch/run` con `{"subcarpeta": "test_batch_1"}`, `GET /batch`, `GET /batch/<batch_id>`)
    - Indicar la ubicación de los resultados: `traces/batch/<batch_id>/summary.json` y una traza por imagen en el mismo directorio, consultables también con `GET /trazas`; limitaciones conocidas (Batch interrumpido sin `summary.json`, Batches concurrentes que comparten la base SQLite)
    - Comandos `python -m api_pruebas` y `uvicorn api_pruebas.app:app`, host por defecto `127.0.0.1`, Swagger en `/docs`
    - Variables `API_TEST_MODE`, `API_TEST_DB_ALLOWLIST`, `API_HOST` y `TRACES_DIR`; regla de base de pruebas (nombre con `test` o `prueba`) y que con `./data/facturas.db` reset y seed responden 403
    - Ejemplos `curl` (incluidos `-F ruta=...` y `-F archivo=@...` para `/ocr`), nota de que `GET /transacciones` no aplica límite por defecto, limitación conocida de la traza que puede no existir, y que la API no importa `mcp`
    - _Requirements: 5.1, 5.11, 5.12, 5.20, 5.21, 7.5, 8.1, 9.1, 9.2, 9.4_

- [x] 13. Checkpoint final - Verificar todo
  - Ejecutar la suite completa (las 63 pruebas existentes y las nuevas); asegurar que todas pasan, preguntar al usuario si surgen dudas.

## Notes

- Las tareas marcadas con `*` son opcionales y se pueden omitir para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los checkpoints validan el avance de forma incremental
- Las pruebas de propiedades validan propiedades universales de corrección (23 propiedades; las 11 a 18 cubren el Batch y las 19 a 23 trazas, permisos, reset/seed, mapeo de errores y advertencia de red); las pruebas unittest validan ejemplos y casos límite
- Endpoints implementados: `POST /ocr`, `POST /validar`, `GET /transacciones`, `POST /pipeline/run`, `POST /batch/run`, `GET /batch`, `GET /batch/{batch_id}`, `GET /trazas`, `GET /trazas/{trace_id}`, `POST /test/reset`, `POST /test/seed`, `/docs` y `/openapi.json`
- La compatibilidad de `fastapi` con `starlette 1.10.0` y `pydantic 2.14.3` se verifica en la tarea 3.1; si no es compatible, se ajusta la versión fijada
- `AutoConfirmIO` reconoce los prompts del Pipeline por texto; la prueba de contrato 8.11 detecta cambios en `agent/agent.py`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "3.1"] },
    { "id": 1, "tasks": ["1.4", "3.2", "4.1", "4.2", "4.5"] },
    { "id": 2, "tasks": ["4.3", "4.4", "4.6", "5.1", "5.2", "5.3"] },
    { "id": 3, "tasks": ["5.4", "5.5", "6.1", "8.1", "8.5", "10.1", "10.2"] },
    { "id": 4, "tasks": ["6.2", "6.4", "8.2", "8.6", "8.7", "8.9"] },
    { "id": 5, "tasks": ["6.3", "8.3", "10.3"] },
    { "id": 6, "tasks": ["8.4", "8.8"] },
    { "id": 7, "tasks": ["8.10", "8.11", "10.4"] },
    { "id": 8, "tasks": ["10.5"] },
    { "id": 9, "tasks": ["10.6", "10.7", "10.8", "10.9", "10.10", "10.11", "10.12", "10.13", "10.14", "10.15", "10.16", "10.17", "10.18", "10.19", "10.20", "10.21", "10.22", "12.1"] }
  ]
}
```
