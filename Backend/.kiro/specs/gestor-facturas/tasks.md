# Implementation Plan: gestor-facturas

## Overview

Plan de implementación incremental del sistema de ingestión de facturas. Las tareas siguen el orden estructural del diseño: estructura del proyecto → capa de datos → lógica de negocio → servidores MCP → agente → CLI → artefactos de runtime → pruebas → evaluación y seguridad → Docker.

Cada tarea produce código que se integra con el trabajo previo; no hay código huérfano.

## Tasks

- [x] 1. Estructura del proyecto y artefactos de configuración
  - Crear el árbol de directorios definido en el diseño: `agent/`, `ocr_mcp/`, `finanzas_mcp/business/`, `finanzas_mcp/db/`, `tests/`, `traces/`, `facturas/`, `eval/`, `security/`
  - Crear `requirements.txt` con las dependencias exactas: `langchain`, `langchain-openai`, `mcp`, `hypothesis`, `python-dotenv`
  - Crear `politica.json` con la estructura definida en el diseño: permisos de herramientas, `step_limit: 8`, `token_limit`, `high_amount_threshold`, `max_date_range_days`, `allowed_filters`
  - Crear `agent/SKILL.md` documentando el procedimiento de seis pasos (Extraer → Validar → Aritmética → Duplicados → Confirmar → Registrar), reglas R1–R11, criterios de parada y tratamiento de contenido no confiable
  - _Requirements: 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 13.4_

- [x] 2. Capa de datos SQLite
  - [x] 2.1 Crear esquema SQLite y repositorio
    - Escribir `finanzas_mcp/db/schema.sql` con la tabla `transactions`, índices `idx_tx_user` e `idx_tx_duplicados`, y constraint `CHECK(moneda IN ('CRC','USD'))`
    - Implementar `finanzas_mcp/db/repository.py`: clase `TransactionRepository` con `__init__(db_path: str)`, `insert(tx: Transaction) -> int`, `find_duplicates(comercio, fecha, total, user_id, limit) -> list[Transaction]`, `query(filters: dict, user_id: str) -> list[Transaction]`
    - El repositorio no debe importar nada de `mcp`, `sys.stdin` o `sys.stdout`
    - _Requirements: 17.3_

  - [x] 2.2 Escribir pruebas de propiedad para aislamiento de usuario (Property 14)
    - **Property 14: User isolation invariant**
    - **Validates: Requirements 10.3**
    - Generar con Hypothesis conjuntos de transacciones de dos usuarios distintos; afirmar que `query` y `find_duplicates` nunca devuelven registros del otro usuario

  - [x] 2.3 Escribir pruebas de propiedad para el límite de resultados de duplicados (Property 7)
    - **Property 7: Duplicate detection result bound**
    - **Validates: Requirements 6.2, 10.3**
    - Insertar un número arbitrario de registros coincidentes; afirmar que `find_duplicates` devuelve como máximo 10 elementos

- [x] 3. Modelos de datos compartidos
  - Implementar `finanzas_mcp/business/categorias.py` con `CLOSED_CATEGORY_LIST`
  - Definir los dataclasses `Transaction`, `ValidationResult`, `OcrResult` en módulos compartidos (`finanzas_mcp/models.py` o equivalente)
  - _Requirements: 7.1, 17.1_

- [x] 4. Lógica de negocio — validación
  - [x] 4.1 Implementar funciones de validación en `finanzas_mcp/business/validacion.py`
    - `validar_campos_obligatorios`: verifica presencia y no-vacío de comercio, fecha, total, moneda, categoría (R1)
    - `validar_fecha`: formato ISO 8601 reconocido y fecha no futura (R2)
    - `validar_moneda`: solo CRC o USD (R3)
    - `validar_aritmetica`: `|subtotal + iva - total| <= 0.01` cuando ambos están presentes (R4)
    - `validar_categoria`: valor en `CLOSED_CATEGORY_LIST` (R6)
    - `validar_monto_alto`: si `total > umbral`, token debe estar presente (R7)
    - `validar_token_confirmacion`: token no nulo y no vacío (R8)
    - Cada función devuelve `ValidationResult(is_valid, errors, error_code)`
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 7.1, 7.2, 8.3, 9.1, 9.2, 9.3_

  - [ ]* 4.2 Escribir pruebas de propiedad para campos obligatorios (Property 3)
    - **Property 3: Required fields invariant**
    - **Validates: Requirements 2.1, 2.2, 2.3**
    - Generar dicts con subconjuntos aleatorios de campos requeridos faltantes; afirmar que siempre se devuelve `MISSING_FIELDS`

  - [ ]* 4.3 Escribir pruebas de propiedad para validez de fecha (Property 4)
    - **Property 4: Date validity invariant**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    - Generar strings de fecha válidos, inválidos y futuros; afirmar aceptación/rechazo correcto

  - [ ]* 4.4 Escribir pruebas de propiedad para lista blanca de moneda (Property 5)
    - **Property 5: Currency whitelist invariant**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Generar strings aleatorios de moneda; afirmar que solo CRC y USD son aceptados

  - [ ]* 4.5 Escribir pruebas de propiedad para coherencia aritmética (Property 6)
    - **Property 6: Arithmetic coherence invariant**
    - **Validates: Requirements 5.1, 5.2, 5.4**
    - Generar tripletas `(subtotal, iva, total)` incoherentes; afirmar que siempre se rechaza

  - [ ]* 4.6 Escribir pruebas de propiedad para lista blanca de categoría (Property 9)
    - **Property 9: Category whitelist invariant**
    - **Validates: Requirements 7.1, 7.2, 7.4**
    - Generar strings de categoría aleatorios; afirmar que solo los valores de `CLOSED_CATEGORY_LIST` son aceptados

  - [ ]* 4.7 Escribir pruebas de propiedad para token de confirmación (Property 10)
    - **Property 10: Confirmation token gates every write**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    - Llamar a `validar_token_confirmacion` con tokens ausentes/vacíos; afirmar rechazo siempre

  - [ ]* 4.8 Escribir pruebas de propiedad para monto alto (Property 11)
    - **Property 11: High-amount confirmation invariant**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - Generar totales por encima del umbral sin `high_amount_token`; afirmar rechazo siempre

- [x] 5. Lógica de negocio — duplicados y transacciones
  - [x] 5.1 Implementar `finanzas_mcp/business/duplicados.py`
    - `buscar_duplicados(repo, comercio, fecha, total, user_id, limit=10)`: delega a `repo.find_duplicates`; aplica `user_id` del contexto de sesión, nunca del payload del agente
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 10.3_

  - [x] 5.2 Implementar `finanzas_mcp/business/transacciones.py`
    - `registrar_transaccion(repo, datos, token, high_amount_token, policy, user_id)`: ejecuta revalidación completa R1–R8 de forma independiente al agente; persiste solo si todo pasa; lanza excepción en caso de violación
    - `listar_transacciones(repo, filtros, user_id, filtros_permitidos, max_rango_dias)`: aplica lista blanca de filtros (R9), máximo rango de fechas, y aislamiento por `user_id`
    - _Requirements: 2.3, 3.4, 4.3, 5.4, 6.4, 6.5, 7.4, 8.3, 8.4, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4_

  - [ ]* 5.3 Escribir pruebas de propiedad para lista blanca de filtros (Property 12)
    - **Property 12: Filter whitelist invariant**
    - **Validates: Requirements 10.1, 10.4**
    - Generar dicts de filtros con claves arbitrarias; afirmar que claves fuera de la lista blanca siempre producen `INVALID_FILTER`

  - [ ]* 5.4 Escribir pruebas de propiedad para ventana de rango de fechas (Property 13)
    - **Property 13: Date-range window invariant**
    - **Validates: Requirements 10.2**
    - Generar rangos de fechas que exceden `max_date_range_days`; afirmar rechazo siempre

- [x] 6. Checkpoint — pruebas de lógica de negocio
  - Asegurarse de que todas las pruebas definidas hasta este punto pasan con `python -m unittest discover -s tests -v`. Consultar al usuario si surgen dudas.

- [x] 7. Servidor MCP `finanzas-mcp`
  - [x] 7.1 Implementar `finanzas_mcp/server.py`
    - Configurar stdin/stdout con `sys.stdin.reconfigure(encoding="utf-8")` y `sys.stdout.reconfigure(encoding="utf-8")`
    - Registrar las cuatro herramientas: `validar_factura`, `buscar_duplicados`, `listar_transacciones`, `registrar_transaccion`
    - Cada handler deserializa el payload, delega a la capa de negocio, serializa la respuesta
    - Errores de negocio → `{"isError": true, "content": [...]}` con mensaje descriptivo; el servidor nunca termina por error de negocio
    - Todo diagnóstico va a `sys.stderr`; nunca `print()` a stdout
    - _Requirements: 17.1, 17.2, 17.4, 17.5_

  - [ ]* 7.2 Escribir pruebas unitarias para el servidor finanzas-mcp
    - Probar que datos inválidos que llegan directamente a `registrar_transaccion` (saltándose `validar_factura`) son rechazados (defensa en profundidad)
    - Al menos una prueba del camino conforme y una del no conforme por cada regla R1–R8
    - _Requirements: 18.1_

- [x] 8. Servidor MCP `ocr-mcp`
  - [x] 8.1 Implementar `ocr_mcp/ocr_client.py`
    - Clase `OcrClient` que envuelve la llamada al LLM con visión (OpenAI GPT-4o o equivalente)
    - Devuelve `OcrResult(text, confidence, is_untrusted=True, low_confidence_fields)`
    - _Requirements: 1.1, 1.5_

  - [x] 8.2 Implementar `ocr_mcp/server.py`
    - Configurar UTF-8 en stdin/stdout
    - Registrar `ocr_imagen(ruta: str)`:
      - Normalizar y resolver `ruta`; rechazar si no está bajo `INVOICES_DIR` (R1.2, R1.4)
      - Verificar extensión (`.jpg`, `.jpeg`, `.png`, `.pdf`) y tamaño ≤ 10 MB (R1.3)
      - Invocar `OcrClient`; devolver `OcrResult` envuelto como contenido no confiable
    - Errores → `isError: true`; servidor nunca termina
    - Todo diagnóstico a `sys.stderr`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 8.3 Escribir pruebas de propiedad para confinamiento de rutas OCR (Property 1)
    - **Property 1: OCR path confinement**
    - **Validates: Requirements 1.2, 1.4**
    - Generar rutas aleatorias dentro y fuera de `INVOICES_DIR`; afirmar que las externas siempre son rechazadas antes de invocar el LLM

  - [ ]* 8.4 Escribir pruebas de propiedad para resultado OCR no confiable (Property 2)
    - **Property 2: OCR result is always marked untrusted**
    - **Validates: Requirements 1.1, 1.5**
    - Para cualquier ruta válida (con LLM mockeado), afirmar que `OcrResult.is_untrusted` siempre es `True`

- [x] 9. Trazador (`agent/tracer.py`)
  - Implementar los dataclasses `TraceEntry` y `Trace` tal como se definen en el diseño
  - Implementar función `write_trace(trace: Trace, traces_dir: str) -> None` que escribe `traces/{timestamp}.json` con encoding UTF-8
  - Si la escritura falla, loguear el error a `sys.stderr` sin interrumpir la interacción del usuario
  - _Requirements: 14.1, 14.2, 14.3_

- [x] 10. Agente LangChain (`agent/agent.py`)
  - [x] 10.1 Implementar carga de política y gestión de límites
    - Leer `politica.json` al arrancar; construir el conjunto de herramientas permitidas, requeridas de confirmación y denegadas
    - Implementar contador de pasos con `StepLimitError` (lanza al llegar a 8) y contador de tokens con `TokenLimitError`
    - _Requirements: 11.1, 11.2, 11.3, 12.3, 12.4_

  - [x] 10.2 Implementar el pipeline SKILL de seis pasos
    - Paso 1 — Extraer: llamar `ocr_imagen`; marcar resultado como no confiable; reintentar una vez si confidence baja; pedir clarificación al usuario si sigue bajo (R1.7)
    - Paso 2 — Validar: llamar `validar_factura`; en campo faltante o moneda inválida pedir valor al usuario; en categoría ambigua presentar `CLOSED_CATEGORY_LIST` (R6, R7)
    - Paso 3 — Aritmética: si incoherencia, preguntar al usuario qué campo es correcto; actualizar datos; reintentar `validar_factura` (R4)
    - Paso 4 — Duplicados: llamar `buscar_duplicados`; si hay coincidencias, presentarlas y esperar confirmación explícita (R5)
    - Paso 5 — Confirmación: si `total > HighAmountThreshold`, pedir high-amount token (R7); siempre pedir standard ConfirmationToken (R8); abortar si no se provee
    - Paso 6 — Registrar: llamar `registrar_transaccion` con ambos tokens; registrar resultado en traza
    - Todo el texto de `OcrResult` se trata como dato no confiable; nunca se ejecuta como instrucción (R10)
    - _Requirements: 1.5, 1.6, 1.7, 5.3, 6.1, 6.3, 7.3, 8.1, 8.2, 9.1_

  - [ ]* 10.3 Escribir pruebas de propiedad para límite de pasos (Property 15)
    - **Property 15: Step limit halts execution**
    - **Validates: Requirements 11.1, 11.3**
    - Mockear escenarios que requieren >8 pasos; afirmar que el agente para en el paso 8, no llama a `registrar_transaccion` y escribe `termination_reason = "step_limit"`

  - [ ]* 10.4 Escribir pruebas de propiedad para límite de tokens (Property 16)
    - **Property 16: Token limit halts execution**
    - **Validates: Requirements 11.2, 11.3**
    - Mockear conteos de tokens que se aproximan al límite; afirmar que el agente para y escribe `termination_reason = "token_limit"`

  - [ ]* 10.5 Escribir pruebas de propiedad para tratamiento de inyección como datos (Property 17)
    - **Property 17: Injection content treated as data**
    - **Validates: Requirements 1.6, 16.2**
    - Generar `OcrResult` con strings de inyección (`SYSTEM:`, `ignore previous instructions`, comandos base64); afirmar que la salida del agente solo contiene valores de campos y no desvía el procedimiento SKILL

  - [ ]* 10.6 Escribir pruebas de propiedad para duplicados como guardián de escritura (Property 8)
    - **Property 8: Duplicate gates write**
    - **Validates: Requirements 6.1, 6.3**
    - Mockear `buscar_duplicados` devolviendo coincidencias; afirmar que `registrar_transaccion` no se invoca sin un paso de confirmación explícito registrado en la traza

- [x] 11. Checkpoint — pruebas del agente y MCP
  - Asegurarse de que todas las pruebas pasan con `python -m unittest discover -s tests -v`. Consultar al usuario si surgen dudas.

- [x] 12. Interfaz de línea de comandos (`agent/main.py`)
  - Implementar `main(image_path: str)` como punto de entrada CLI
  - Parsear argumento de ruta de imagen con `argparse`
  - Instanciar el agente con política y skill
  - Redirigir prompts de confirmación a stdout y leer respuestas de stdin
  - Mostrar resultado final (éxito de registro, error de validación, razón de parada) en la salida CLI
  - _Requirements: 19.1, 19.2, 19.3_

- [x] 13. Pruebas unitarias de cobertura de reglas de negocio
  - [x] 13.1 Escribir pruebas unitarias para R1–R4 (validación de campos, fecha, moneda, aritmética)
    - Al menos una prueba conforme y una no conforme por cada regla
    - Mockear todas las dependencias externas (LLM, MCP)
    - _Requirements: 18.1, 18.2, 18.3_

  - [x] 13.2 Escribir pruebas unitarias para R5–R8 (duplicados, categoría, confirmación)
    - Al menos una prueba conforme y una no conforme por cada regla
    - Probar flujo de revalidación de `registrar_transaccion` con datos que saltaron `validar_factura`
    - _Requirements: 18.1, 18.2, 18.3_

  - [x] 13.3 Escribir pruebas unitarias para R9–R11 (filtros, aislamiento, límites)
    - Al menos una prueba conforme y una no conforme por cada regla
    - Probar que el trazador escribe correctamente y que los errores de escritura van a stderr
    - _Requirements: 18.1, 18.2, 18.3_

- [x] 14. Infraestructura de evaluación y análisis de seguridad
  - [x] 14.1 Crear estructura del conjunto de evaluación en `eval/`
    - Crear `eval/labels.csv` con las columnas: `imagen`, `comercio`, `fecha`, `total`, `moneda`, `categoria`, `tipo` (`clean`/`difficult`), `dificultad` (blurry/tilted/discount/duplicate/injection), `anotador_1_*`, `anotador_2_*`, `kappa_categoria`, `acuerdo_*`
    - Crear `eval/README.md` documentando la estructura del conjunto, criterios de etiquetado y procedimiento para calcular Cohen's kappa y acuerdo porcentual
    - Asegurarse de que el CSV contiene marcadores de posición para ≥45 facturas (18 limpias, 27 difíciles distribuidas según Req 15.2)
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [x] 14.2 Crear plantilla de análisis de seguridad en `security/injection_analysis.md`
    - Documentar los 5 escenarios de ataque de inyección definidos en el diseño: override `SYSTEM:`, instrucción en nombre de comercio, SQL injection en campo total, instrucción base64, instrucciones multi-línea en descripción de producto
    - Para cada escenario: descripción del ataque, texto de instrucción embebido, respuesta observada del sistema (a completar durante la ejecución real), resultado (bloqueado/exitoso)
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

- [x] 15. Docker
  - Crear `Dockerfile` basado en `python:3.12-slim`; copiar el proyecto, instalar dependencias, configurar `VOLUME ["/app/data"]`, `ENV DB_PATH=/app/data/facturas.db`, `ENV INVOICES_DIR=/app/facturas`, `CMD ["python", "-m", "agent.main"]`
  - Crear `docker-compose.yml` que mapea el volumen `/app/data` a una carpeta del host y el directorio de facturas
  - _Requirements: 20.1, 20.2, 20.3_

- [x] 16. Checkpoint final — suite completa
  - Ejecutar `python -m unittest discover -s tests -v` y verificar que todos los tests pasan sin dependencias de red externas
  - Confirmar que `politica.json`, `SKILL.md`, `Dockerfile` y `docker-compose.yml` existen y son coherentes con el diseño
  - Consultar al usuario si surgen dudas o si algún test falla de forma no determinista.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia los requisitos específicos para trazabilidad
- La capa `finanzas_mcp/business/` no debe importar `mcp`, `sys.stdin` ni `sys.stdout` en ningún momento; esto habilita la transición futura a backend REST
- `user_id` siempre se inyecta desde el contexto de sesión del servidor MCP, nunca se toma del payload del agente (defensa contra escalada de privilegios)
- Todos los archivos se leen y escriben con `encoding="utf-8"` (regla técnica del curso)
- El trazador escribe errores a `sys.stderr` sin interrumpir la interacción del usuario
- Las pruebas de propiedad usan Hypothesis con un mínimo de 100 iteraciones por propiedad

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "3.1"] },
    { "id": 1, "tasks": ["4.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["5.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8"] },
    { "id": 3, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 4, "tasks": ["7.1", "8.1", "9.1"] },
    { "id": 5, "tasks": ["7.2", "8.2"] },
    { "id": 6, "tasks": ["8.3", "8.4", "10.1"] },
    { "id": 7, "tasks": ["10.2"] },
    { "id": 8, "tasks": ["10.3", "10.4", "10.5", "10.6", "12.1"] },
    { "id": 9, "tasks": ["13.1", "13.2", "13.3"] },
    { "id": 10, "tasks": ["14.1", "14.2", "15.1"] }
  ]
}
```
