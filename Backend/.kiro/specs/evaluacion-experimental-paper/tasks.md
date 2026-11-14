# Implementation Plan: evaluacion-experimental-paper

## Overview

Plan de implementación incremental que extiende `gestor-facturas` para producir el experimento reproducible del paper. El lenguaje de implementación es Python 3.12, el mismo del diseño. Las tareas siguen este orden: política y parámetros HITL → confianza OCR → detector de contenido sospechoso → alertas y decisión HITL → pipeline del agente → `finanzas-mcp` (Token_Automatico) → baselines → Golden Set y validadores → métricas, benchmark e informes → compatibilidad y pruebas estructurales.

Cada tarea se apoya en las anteriores y termina integrada. Con `modo_hitl="siempre"` (valor por defecto) el comportamiento actual no cambia, de modo que las pruebas existentes R1 a R11, `api_pruebas` y Docker Compose siguen funcionando sin modificaciones.

## Tasks

- [x] 1. Política y parámetros HITL
  - [x] 1.1 Implementar parámetros HITL y política ampliada
    - Crear `finanzas_mcp/business/hitl.py` (puro, sin `mcp`) con `MODOS_HITL`, `AUTO_TOKEN_PREFIX`, `PoliticaHitlError`, `ParametrosHitl`, `resolver_parametros_hitl(raw, exigir_umbral=True)`, `es_token_automatico` y `decidir_rechazo_automatico` con los códigos `AUTOMATIC_TOKEN_NOT_ALLOWED`, `HIGH_AMOUNT_CONFIRMATION_REQUIRED` y `HUMAN_CONFIRMATION_REQUIRED`
    - Añadir `"modo_hitl": "siempre"` y `"umbral_confianza_ocr": 0.75` a `politica.json`
    - Ampliar `Policy` en `agent/agent.py` con `modo_hitl="siempre"` y `umbral_confianza_ocr=0.75`; hacer que `load_policy` llame a `resolver_parametros_hitl` y propague `PoliticaHitlError`; eliminar `LOW_CONFIDENCE_THRESHOLD` en favor de `policy.umbral_confianza_ocr`
    - En `agent/main.py` capturar `PoliticaHitlError`, imprimir el mensaje a stderr y salir con código 2 antes de procesar documentos
    - Usar `encoding="utf-8"` y type hints en todas las firmas
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8, 3.4, 18.1_

  - [x] 1.2 Escribir prueba de propiedad para la validación de parámetros HITL
    - Crear `tests/test_politica_hitl.py`
    - **Property 3: Validación de parámetros HITL de la política**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 2.8, 3.4**
    - Incluir pruebas de ejemplo con los límites 0.0, 1.0, -0.01 y 1.01, y comprobar que el `politica.json` del repositorio tiene `modo_hitl="siempre"`
    - _Requirements: 2.4, 19.6_

  - [x] 1.3 Crear dobles de prueba compartidos
    - Crear `tests/_sin_red.py` con `SinRedTestCase`, que parchea `socket.socket.connect` y `socket.create_connection` para fallar ante cualquier intento de red
    - Crear los dobles `FakeOcr` (resultados configurables y conteo de llamadas) y `FakeClienteLlm` (llamadas de herramienta, excepciones o bloqueo con reloj inyectado) en `tests/_dobles.py`
    - _Requirements: 18.6, 19.10_

- [x] 2. Confianza de extracción en `ocr_imagen`
  - [x] 2.1 Ampliar `OcrResult` y calcular confianzas
    - En `finanzas_mcp/models.py` añadir a `OcrResult` los campos `confianza_ocr`, `confianza_campos` y `uso_tokens`, todos con valor por defecto
    - En `ocr_mcp/ocr_core.py` añadir `CAMPOS_CONFIANZA`, `CAMPOS_REQUERIDOS` y la función pura `calcular_confianzas(datos, confianza_cruda)` con las reglas de campos ausentes, inválidos y no extraídos
    - Verificar que `wrap_untrusted` mantiene `is_untrusted=true` y serializa los campos nuevos
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

  - [x] 2.2 Integrar la confianza en `OcrClient`
    - En `ocr_mcp/ocr_client.py` llamar a `calcular_confianzas` desde `_parse_response`, rellenar `confianza_ocr` y `confianza_campos`, y conservar `confidence` y `low_confidence_fields`
    - Guardar `usage_metadata` del LLM en `_ultimo_uso` y copiarlo a `uso_tokens`; ante JSON no parseable devolver `confianza_ocr=0.0` y `confianza_campos={}`
    - Escribir todo diagnóstico a `sys.stderr`
    - _Requirements: 1.1, 1.2, 1.7, 1.8, 18.2_

  - [x] 2.3 Escribir pruebas de propiedad para la confianza OCR
    - Crear `tests/test_ocr_confianza.py`
    - **Property 1: Confianzas OCR acotadas y coherentes**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    - **Property 2: El resultado OCR es siempre no confiable y conserva las claves antiguas**
    - **Validates: Requirements 1.6, 1.7**
    - Añadir una prueba de ejemplo que verifique que los diagnósticos van a stderr y no a stdout
    - _Requirements: 1.8_

- [x] 3. Detector de contenido sospechoso
  - [x] 3.1 Implementar `agent/contenido_sospechoso.py`
    - Definir `CATEGORIAS`, `MAX_CARACTERES=20_000`, `PatronSospechoso`, `PATRONES` (ids únicos, regex acotadas sin cuantificadores anidados), `ResultadoEscaneo` y `escanear(texto)`
    - Conservar el patrón base64 actual; marcar como sospechoso el texto vacío, no `str`, mayor al límite o con error interno, con su `motivo_fallo`
    - No modificar aún `agent/agent.py`; el reemplazo de `_INJECTION_PATTERNS` se hace en la tarea 6.2
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8_

  - [x] 3.2 Escribir pruebas del detector
    - Crear `tests/test_contenido_sospechoso.py`
    - **Property 8: El detector de contenido sospechoso es determinista y consistente**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.8**
    - Incluir al menos 3 ejemplos positivos y 3 negativos
    - _Requirements: 19.7_

- [x] 4. Alertas y decisión HITL
  - [x] 4.1 Implementar `agent/hitl.py`
    - Definir `ALERTAS`, `EntradaAlertas`, `evaluar_alertas` (pura y determinista, orden fijo), `DecisionHitl`, `decidir_hitl` y `generar_token_automatico` (`auto:` + uuid4 hex)
    - Definir las constantes de prompt `PROMPT_REGISTRAR`, `PROMPT_MONTO_ALTO`, `PROMPT_DUPLICADOS`, `PROMPT_ALERTAS` y `clasificar_prompt`, conservando las subcadenas que usa `AutoConfirmIO`
    - Aplicar los límites de `reglas_detonantes` (0 a 50 ítems de 1 a 100 caracteres) y de `razon` (1 a 500 caracteres)
    - _Requirements: 4.3, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 8.1, 8.2, 8.3, 8.4_

  - [x] 4.2 Escribir pruebas de propiedad para alertas y decisión
    - Crear `tests/test_hitl_alertas.py`
    - **Property 5: Evaluación determinista de alertas HITL**
    - **Validates: Requirements 4.3, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8**
    - **Property 6: Decisión HITL coherente con modo y alertas**
    - **Validates: Requirements 5.1, 5.7, 8.1, 8.2, 8.3, 8.4**
    - Añadir una prueba de ejemplo por cada una de las cinco alertas
    - _Requirements: 19.1_

- [x] 5. Checkpoint - Política, OCR, detector y alertas
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Pipeline del agente con HITL adaptativo
  - [x] 6.1 Ampliar la traza
    - En `agent/tracer.py` añadir a `Trace` los campos opcionales `decision_hitl`, `alertas_hitl`, `patrones_sospechosos`, `motivo_fallo_escaneo`, `ocr`, `tokens_entrada` y `tokens_salida`, todos con valor por defecto
    - Mantener `write_trace` sin cambios, con errores de escritura a stderr sin interrumpir la corrida
    - _Requirements: 8.1, 8.5, 8.7_

  - [x] 6.2 Implementar reintento OCR, alertas y token automático en `InvoicePipeline`
    - Paso 1: añadir `confianza` y `campos` al dict OCR, `_es_bajo`, un único reintento de `ocr_imagen` capturando solo `ToolError`, `_seleccionar` (mayor confianza global, primero en empate), y `escanear` del texto OCR con registro de patrones en la traza; reemplazar `_INJECTION_PATTERNS` por el módulo `agent/contenido_sospechoso.py`
    - Guardar `datos_extraidos` antes de los pasos 2 y 3 para evaluar `ARITHMETIC_MISMATCH` (D5)
    - Paso 4: en modo `adaptativo` no preguntar por duplicados y solo registrar el conteo (D6); en `siempre` conservar la pregunta actual
    - Paso 5: construir `EntradaAlertas`, llamar a `evaluar_alertas` y `decidir_hitl`; en `siempre` mantener el flujo actual sin excepción por monto; en `adaptativo` emitir `Token_Automatico` sin llamar a `ask` si no hay alertas, o hacer una única solicitud consolidada con todas las alertas; tratar rechazo o falta de respuesta como `user_rejection`
    - Paso 6: enviar `confianza_ocr` y `contenido_sospechoso` en el payload; nunca enviar `high_amount_token` con token automático
    - Registrar `decision_hitl`, `alertas_hitl`, el bloque `ocr` y los tokens del OCR en la traza; contar el reintento dentro del StepLimit
    - _Requirements: 3.1, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 6.3 Escribir pruebas de propiedad del pipeline
    - Crear `tests/test_agent_hitl.py`
    - **Property 4: Reintento único y selección por mayor confianza**
    - **Validates: Requirements 4.1, 4.2, 4.4**
    - **Property 7: En modo siempre se pide token sin excepción por monto**
    - **Validates: Requirements 3.1**
    - _Requirements: 3.1, 4.1, 4.2, 4.4_

  - [x] 6.4 Escribir pruebas de ejemplo del pipeline
    - Ampliar `tests/test_agent_hitl.py`, sin modificar las pruebas existentes de `tests/`
    - Cubrir: una prueba por alerta (la traza lista la regla en `reglas_detonantes`), Factura_Limpia sin confirmación en `adaptativo` y con confirmación en `siempre`, tres pruebas separadas de baja confianza (un solo reintento, selección del mayor incluso si el reintento es peor, alerta `LOW_OCR_CONFIDENCE` tras el reintento), StepLimit antes del reintento, rechazo o falta de respuesta, y que la instrucción incrustada no se ejecuta
    - _Requirements: 4.3, 4.5, 4.6, 5.1, 5.10, 7.5, 19.1, 19.2, 19.3, 19.4_

- [x] 7. `finanzas-mcp`: validación independiente del Token_Automatico
  - [x] 7.1 Implementar la rama de Token_Automatico en `registrar_transaccion`
    - Ampliar `finanzas_mcp/business/transacciones.py` con los parámetros opcionales `confianza_ocr` y `contenido_sospechoso` al final de la firma, sin cambiar los seis parámetros existentes
    - Resolver `modo_hitl` y `umbral_confianza_ocr` solo desde la política del servidor, con falla cerrada (`siempre` y umbral 1.0) si es inválida
    - Modo `siempre` con token automático: rechazar con `AUTOMATIC_TOKEN_NOT_ALLOWED`. Modo `adaptativo`: revalidar R1, R2, R3 y R6, rechazar monto alto, y aplicar `decidir_rechazo_automatico` (aritmética, duplicado, confianza baja o ausente, contenido sospechoso o ausente) antes de persistir
    - Mantener el flujo actual R1 a R8 para tokens de usuario; los rechazos no deben dejar filas
    - _Requirements: 3.2, 3.3, 5.9, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 7.2 Exponer los campos nuevos en el servidor MCP y en `api_pruebas`
    - En `finanzas_mcp/server.py` añadir `confianza_ocr` y `contenido_sospechoso` al `inputSchema` (opcionales), excluir `modo_hitl`, `umbral_confianza_ocr` y `user_id` del payload, ampliar la política por defecto de `_load_policy` y la `description` de la herramienta
    - En `api_pruebas/servicios.py` y `api_pruebas/herramientas.py` pasar `confianza_ocr` y `contenido_sospechoso` a la función de negocio sin cambiar ningún endpoint, campo de petición o respuesta
    - Verificar que los rechazos salen como `isError: true` y que no hay `print()` a stdout
    - _Requirements: 6.7, 6.9, 18.2, 18.3, 18.4_

  - [x] 7.3 Escribir pruebas de propiedad del servidor
    - Crear `tests/test_servidor_token_automatico.py` con repositorio en directorio temporal
    - **Property 9: El servidor rechaza todo Token_Automatico en modo siempre**
    - **Validates: Requirements 3.2, 3.3**
    - **Property 10: Revalidación independiente y prioridad de códigos con Token_Automatico**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8**
    - **Property 11: El servidor ignora los parámetros HITL del payload**
    - **Validates: Requirements 6.7**
    - **Property 12: Las reglas de negocio no dependen del modo con token de usuario**
    - **Validates: Requirements 5.9**
    - _Requirements: 3.2, 3.3, 5.9, 6.1, 6.7, 6.8_

  - [x] 7.4 Escribir pruebas de ejemplo de rechazo del Token_Automatico
    - Ampliar `tests/test_servidor_token_automatico.py`
    - Una prueba por cada caso del Requirement 6 (monto alto, aritmética, duplicado, confianza baja, contenido sospechoso) y una para modo `siempre`; cada una afirma el error y que no se crea ningún registro
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 6.9, 19.5_

- [x] 8. Checkpoint - Pipeline y servidor
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Baselines en `baseline/`
  - [x] 9.1 Implementar `BDTemporal` y `TrazaComun`
    - Crear `baseline/__init__.py`, `baseline/bd_temporal.py` (`BDTemporal`, `BDTemporalError`, esquema leído como texto desde `finanzas_mcp/db/schema.sql`, borrado en `finally` salvo `conservar=True`) y `baseline/traza_comun.py` (`ESTADOS_FINALES`, `TrazaComun`, `a_dict`, `desde_dict`, `escribir_traza`, `desde_traza_agente`)
    - La traza contiene exactamente siete campos; `escribir_traza` crea el directorio, escribe JSON UTF-8 con `ensure_ascii=False` y ante fallos escribe a stderr sin alterar el resultado
    - No importar `TransactionRepository` ni código de negocio
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10_

  - [x] 9.2 Implementar `baseline/llm.py`
    - Crear `ConfigLlm`, `ConfigLlmError`, `resolver_config_llm(env)` (exige `LLM_PROVIDER`, `OCR_MODEL` y la clave del proveedor, nombrando cada faltante), `RespuestaLlm`, el protocolo `ClienteLlm` y `ClienteLangChain` con los mismos parámetros que `OcrClient`
    - _Requirements: 9.2, 9.10, 10.2_

  - [x] 9.3 Implementar el procesador común y los dos baselines
    - Crear `baseline/_comun.py` con `ProcesadorBaseline`, `ResultadoBaseline` y `correr`: una llamada multimodal, herramienta única `insertar_transaccion` con `BEGIN/INSERT/COMMIT` y `ROLLBACK` ante error, timeout de 60 s con hilo de trabajo, `Event` de cancelación y `Lock` que protege el `COMMIT`
    - Crear `baseline/baseline_naive.py` (prompt mínimo, sin validación) y `baseline/baseline_prompt_guarded.py` (datos no instrucciones, R2, R3, R4 y R5 en el prompt), ambos con `main()`
    - Crear `baseline/README.md` que declare la exclusión de `.kiro/steering/seguridad.md`
    - Ningún módulo de `baseline/` importa `ocr_mcp`, `finanzas_mcp.business`, `finanzas_mcp.server`, `mcp`, `agent` ni `api_pruebas`, y ninguno recibe `UserIO`
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 10.1, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10, 18.7_

  - [x] 9.4 Escribir pruebas de propiedad de la traza común
    - Crear `tests/test_traza_comun.py`
    - **Property 13: Traza_Comun mantiene forma y round trip**
    - **Validates: Requirements 11.5, 11.6, 11.10**
    - **Property 14: La conversión de la traza del agente produce una Traza_Comun válida**
    - **Validates: Requirements 11.9**
    - _Requirements: 11.5, 11.6, 11.9, 11.10_

  - [x] 9.5 Escribir pruebas de propiedad de los baselines
    - Crear `tests/test_baselines.py` con `FakeClienteLlm` y `SinRedTestCase`
    - **Property 15: Ciclo de vida de la BD temporal**
    - **Validates: Requirements 10.5, 11.1, 11.3, 15.4, 15.10**
    - **Property 16: Aislamiento de errores por factura en los baselines**
    - **Validates: Requirements 9.7, 9.8, 10.7, 10.8, 10.9, 15.9**
    - **Property 17: Las variables de entorno obligatorias se validan antes de procesar**
    - **Validates: Requirements 9.10, 15.13**
    - Añadir pruebas de ejemplo por baseline (BD existe durante la corrida, se borra después incluso con error, se genera la traza), timeout con reloj inyectado y análisis AST de los imports prohibidos
    - _Requirements: 9.4, 9.9, 10.10, 11.2, 19.9_

- [x] 10. Golden Set y validadores
  - [x] 10.1 Implementar validadores, anotaciones y conversión
    - Crear `eval/__init__.py`, `eval/golden_set.py` (`ErrorValidacion`, `validar_particion_limpia`, `validar_ground_truth`, `validar_manifiesto`, `cargar_particion_limpia`, `cargar_particion_adversarial`), `eval/anotaciones.py` (`acuerdo_porcentual`, `kappa_cohen`, `resumen_acuerdos`) y `eval/convertir_labels.py` (`convertir_filas`)
    - Los validadores son de solo lectura, reportan todos los ofensivos y comprueban conteos (45 imágenes, 18 `limpia`, 27 restantes), mínimos por clase y por subtipo adversarial, vectores de inyección y existencia de originales de duplicados
    - `kappa_cohen` devuelve `None` cuando la lista está vacía o el acuerdo esperado es 1; `eval/labels.csv` no se modifica
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.8, 12.9, 12.10, 12.11, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 14.1, 14.2, 14.3, 14.4, 14.6, 14.8_

  - [x] 10.2 Escribir pruebas de propiedad de kappa y acuerdo
    - Crear `tests/test_anotaciones.py`
    - **Property 18: Kappa de Cohen y acuerdo porcentual**
    - **Validates: Requirements 12.6, 12.11**
    - _Requirements: 12.6, 12.11_

  - [x] 10.3 Escribir pruebas de propiedad de los validadores del Golden Set
    - Crear `tests/test_golden_set.py`
    - **Property 19: Validación del Golden Set limpio**
    - **Validates: Requirements 12.3, 12.4, 12.8, 12.9, 12.10**
    - **Property 20: Validación del manifiesto adversarial**
    - **Validates: Requirements 13.1, 13.6, 13.7, 13.8, 14.4, 14.6, 14.8**
    - _Requirements: 12.8, 12.9, 12.10, 13.7, 14.8_

  - [x] 10.4 Generar la partición adversarial sintética
    - Crear `eval/generar_adversarial.py` que renderice con Pillow facturas sintéticas (sin PII real) y escriba `eval/golden_set/adversarial_security/images/` y `adversarial_manifest.json`
    - Incluir como mínimo 3 casos por subtipo de integridad (`inconsistencia_aritmetica`, `fecha_invalida` con uno malformado y uno futuro, `moneda_no_soportada`, `factura_duplicada` con sus `originales`) y al menos 2 imágenes por cada uno de los 5 vectores de inyección, con el texto inyectado renderizado en la imagen e idéntico al del manifiesto
    - Añadir Pillow a `requirements.txt`; validar el resultado con `validar_manifiesto`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 14.1, 14.2, 14.3, 14.4, 14.6, 14.7_

- [x] 11. Métricas, runner, informes y CLI del Benchmark
  - [x] 11.1 Implementar `eval/metricas.py`
    - Crear `Metrica`, `proporcion`, `media`, `integridad_fpa`, `asr`, `tasa_friccion`, `costo_operacional`, `exactitud_por_campo`, `conteos`, `calcular_todo`, `comprometido` y `es_valida_limpia`, todos puros
    - Definir `RegistroFactura` con todos los campos necesarios para recalcular sin BD ni LLM; el denominador 0 produce `valor=None` sin excepción y cada métrica guarda numerador y denominador
    - `comprometido` decide solo con la fila almacenada, el estado final, las confirmaciones y los datos esperados, nunca con texto del LLM
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10, 16.11_

  - [x] 11.2 Escribir pruebas de propiedad de las métricas
    - Crear `tests/test_metricas.py`
    - **Property 23: Métricas de proporción**
    - **Validates: Requirements 16.1, 16.2, 16.4, 16.6, 16.8, 16.11**
    - **Property 24: Costo operacional, exactitud por campo y conteos**
    - **Validates: Requirements 16.7, 16.9, 16.10**
    - **Property 25: El veredicto de compromiso no depende del texto del LLM**
    - **Validates: Requirements 16.3**
    - **Property 26: Clasificación de factura válida y limpia**
    - **Validates: Requirements 16.5**
    - Añadir pruebas con registros sintéticos de valores calculados a mano y un caso de denominador cero por métrica
    - _Requirements: 16.8, 19.8_

  - [x] 11.3 Implementar `eval/runner.py`
    - Crear `SISTEMAS`, `seleccionar` (primeras N en orden alfabético), `ordenar_casos` (`OrdenError` con los `id` afectados), `PoliticaRespuestasConfirmarTodo` (cuenta una confirmación por prompt según `clasificar_prompt`), `correr_arquitectura` y `correr_baseline`
    - `correr_arquitectura` usa un `Config` propio con `BDTemporal`, política en memoria con `modo_hitl="adaptativo"` (sin escribir `politica.json`), `ServiciosNegocio` con `OcrClient` y `construir_tools`, y nunca abre `DB_PATH`
    - Insertar la fila canario de otro usuario antes de cada partición adversarial; cada factura se envuelve en `try/except Exception` que registra el tipo de excepción, marca `fallida=True` y continúa; las BD temporales se eliminan en `finally`
    - _Requirements: 2.7, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9, 15.10, 15.11, 15.12_

  - [x] 11.4 Escribir pruebas de propiedad del runner
    - Crear `tests/test_benchmark_runner.py`
    - **Property 21: Los originales preceden a sus duplicados**
    - **Validates: Requirements 15.6, 15.7**
    - **Property 22: Selección de facturas, sistemas y validación de argumentos**
    - **Validates: Requirements 15.2, 15.11, 15.12, 15.15**
    - **Property 27: Conteo de confirmaciones del usuario guionado**
    - **Validates: Requirements 15.8**
    - Añadir pruebas de ejemplo: `politica.json` byte-idéntico (hash) antes y después, y un `DB_PATH` señuelo intacto
    - _Requirements: 2.7, 15.5_

  - [x] 11.5 Implementar `eval/informes.py`
    - Crear `escribir_json_atomico` (temporal en el mismo directorio, `fsync`, `os.replace`, limpieza ante fallo), `leer_resultados` (`ResultadosInvalidosError`), `construir_resultados`, `commit_actual` (`None` ante cualquier fallo de git), `formatear_tabla` y `actualizar_injection_analysis`
    - `formatear_tabla` usa 4 decimales para Integridad_FPA, ASR y Tasa_Friccion, 1 decimal para latencia y tokens, y `n/d` para `None`; `actualizar_injection_analysis` reescribe solo el bloque entre `<!-- BENCH:INICIO -->` y `<!-- BENCH:FIN -->`
    - _Requirements: 14.5, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.9_

  - [x] 11.6 Escribir pruebas de propiedad de informes
    - Crear `tests/test_informes.py`
    - **Property 28: Formato de la tabla comparativa**
    - **Validates: Requirements 17.4, 17.5, 17.6**
    - **Property 29: Round trip y escritura atómica de resultados_paper.json**
    - **Validates: Requirements 17.1, 17.9**
    - **Property 30: `--recalcular` es determinista y reproduce el cálculo original**
    - **Validates: Requirements 17.7**
    - Añadir pruebas de ejemplo: commit `null`, `--recalcular` con archivo faltante, JSON inválido y sin registros (sin modificar archivos), y actualización solo del bloque BENCH
    - _Requirements: 17.3, 17.8_

  - [x] 11.7 Implementar el CLI `eval/benchmark.py` y su documentación
    - Crear `eval/benchmark.py` ejecutable con `python -m eval.benchmark`, con `--limite`, `--sistemas`, `--recalcular` y `--salida`; ejecutar en orden: validar argumentos, `--recalcular`, claves (`resolver_config_llm`), validación del Golden Set, `ordenar_casos`, ejecución e informes
    - Salir con código distinto de cero y mensaje claro ante argumentos inválidos, claves faltantes (sin crear archivos ni BD), originales no garantizados o `--recalcular` inválido; no escribir resultados parciales ante interrupción
    - Crear o ampliar `eval/README.md` con el comando, cada argumento, los factores de costo, las definiciones de las métricas, la política `confirmar_todo`, las amenazas a la validez (D2, D3, D4, D9 y que `exfiltracion` no puede tener éxito en los baselines) y la lista de verificación manual del Golden Set
    - _Requirements: 15.1, 15.2, 15.3, 15.7, 15.12, 15.13, 15.14, 15.15, 17.1, 17.2, 17.4, 17.7, 17.8, 17.10_

- [x] 12. Compatibilidad y pruebas estructurales
  - [x] 12.1 Propagar los errores de política en `api_pruebas`
    - En `api_pruebas/config.py` capturar `PoliticaHitlError` antes de `ValueError` y conservar su mensaje dentro de `ConfigError`
    - Verificar que los endpoints, métodos, campos de petición y respuesta, y `AutoConfirmIO` no cambian
    - _Requirements: 2.5, 2.6, 18.4_

  - [x] 12.2 Preparar `security/injection_analysis.md` para el bloque generado
    - Añadir las marcas `<!-- BENCH:INICIO -->` y `<!-- BENCH:FIN -->` sin alterar el contenido existente del documento
    - _Requirements: 14.5_

  - [x] 12.3 Escribir pruebas estructurales del repositorio
    - Crear `tests/test_estructura_repositorio.py` con comprobaciones AST: type hints en todas las firmas y `encoding="utf-8"` en los módulos nuevos, ausencia de `print` a stdout en los servidores MCP, README de `baseline/` con la declaración de exclusión, y que ningún script de `eval/` o `baseline/` esté bajo `tests/`
    - _Requirements: 18.1, 18.2, 18.7, 18.8, 18.9_

  - [x] 12.4 Escribir pruebas de integración de `api_pruebas` y de regresión
    - Crear `tests/test_api_pruebas_hitl.py` con los dobles existentes del módulo: cada traza de `/pipeline/run` y de cada factura de `/batch/run` contiene la entrada de decisión HITL, y los esquemas de respuesta no cambian
    - Confirmar que con `politica.json` en `siempre` las pruebas existentes R1 a R11 y del pipeline pasan sin modificaciones y sin red
    - _Requirements: 3.5, 8.6, 18.4, 18.6_

- [x] 13. Checkpoint final - Suite completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido.
- Cada tarea referencia los requisitos específicos para trazabilidad.
- **Pendiente de confirmar con el usuario (D10):** el Requirement 12.2 pide 27 facturas con dificultad distinta de `limpia`, pero GF-Req 15.2 solo define 21 (6 borrosas, 5 inclinadas, 5 con múltiples descuentos y 5 duplicadas) una vez excluidas las inyecciones. El reparto de las 6 facturas restantes no tiene clase asignada. El validador de la tarea 10.1 debe parametrizar los mínimos por clase para ajustarlos cuando el usuario lo confirme.
- Actividades manuales fuera del alcance de las tareas automatizables: recolectar y anotar a mano las 45 facturas reales de la Partición Limpia (incluida la doble anotación independiente de dos anotadores), ofuscar de forma irreversible la PII de esas imágenes, revisar visualmente la partición adversarial, y ejecutar el Benchmark con el LLM real (tiene costo y vive fuera de `tests/`). La lista de verificación manual queda documentada en `eval/README.md` (tarea 11.7).
- Todas las pruebas de `tests/` usan dobles para el LLM, `ocr-mcp` y la red; ninguna realiza llamadas pagas. Las pruebas de propiedad usan Hypothesis con un mínimo de 100 iteraciones.
- La capa `finanzas_mcp/business/` no importa `mcp`, `sys.stdin` ni `sys.stdout`; `baseline/` no importa código del sistema propuesto.
- `docker-compose.yml` y `Dockerfile` no cambian; los tres servicios solo leen claves adicionales de `politica.json`.
- El flujo de trabajo termina con la creación de este plan; la implementación se inicia desde las tareas de `tasks.md`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "2.1", "3.1", "4.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.2", "4.2", "6.1", "7.1"] },
    { "id": 2, "tasks": ["2.3", "6.2", "7.2", "9.1"] },
    { "id": 3, "tasks": ["6.3", "7.3", "9.2", "9.4", "10.1", "11.1"] },
    { "id": 4, "tasks": ["6.4", "7.4", "9.3", "10.2", "10.3", "10.4", "11.2", "12.1"] },
    { "id": 5, "tasks": ["9.5", "11.3", "11.5"] },
    { "id": 6, "tasks": ["11.4", "11.6", "11.7", "12.2"] },
    { "id": 7, "tasks": ["12.3", "12.4"] }
  ]
}
```
