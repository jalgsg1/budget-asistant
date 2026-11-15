# Requirements Document

## Introduction

Las listas de valores cerrados del Backend (monedas, categorías, modos HITL, alertas, estados del pipeline, dificultades del Golden Set, sistemas evaluados, etc.) están definidas en muchos módulos. Esta funcionalidad las centraliza en un archivo `constantes.py` por paquete (`finanzas_mcp`, `agent`, `eval`, `baseline`), de modo que exista un único lugar por paquete donde consultarlas.

Las constantes se agrupan como valores de módulo (`tuple`, `frozenset`, `dict`, `list`, `str`, `int`). No se usan clases `Enum`. Los valores no cambian: los textos, el orden y el tipo se conservan, de modo que JSON, CSV, manifiesto adversarial y `politica.json` quedan idénticos. Los módulos actuales importan desde el nuevo archivo y conservan sus nombres antiguos como alias.

## Glossary

- **Constantes_Finanzas**: módulo `finanzas_mcp/constantes.py`.
- **Constantes_Agent**: módulo `agent/constantes.py`.
- **Constantes_Eval**: módulo `eval/constantes.py`.
- **Constantes_Baseline**: módulo `baseline/constantes.py`.
- **Archivos_Constantes**: conjunto de los cuatro módulos anteriores.
- **Modulo_Origen**: módulo que hoy define una constante (por ejemplo `finanzas_mcp/business/categorias.py`).
- **Alias_Compatible**: nombre antiguo que el Modulo_Origen sigue exponiendo y que referencia el mismo objeto definido en el Archivo_Constantes de su paquete.
- **Valor_Original**: valor de una constante antes del cambio, congelado como literal en `tests/test_constantes.py`.
- **Suite_Completa**: ejecución de `python -m pytest tests -q` desde `Backend`.
- **Prueba_Constantes**: archivo `tests/test_constantes.py`.
- **Tabla_Alias**: lista de tuplas (módulo, nombre antiguo, archivo de constantes, nombre nuevo) que usa la Prueba_Constantes.

## Requirements

### Requirement 1: Archivo de constantes por paquete

**User Story:** As a desarrollador del Backend, I want un archivo de constantes por paquete, so that sé en un solo lugar de cada paquete dónde están las listas de valores.

#### Acceptance Criteria

1. THE Backend SHALL contener los cuatro archivos `finanzas_mcp/constantes.py`, `agent/constantes.py`, `eval/constantes.py` y `baseline/constantes.py`.
2. THE Archivos_Constantes SHALL definir cada valor como constante de módulo con tipo `tuple`, `frozenset`, `dict`, `list`, `str` o `int`.
3. THE Archivos_Constantes SHALL omitir las clases `Enum`.
4. THE Archivos_Constantes SHALL anotar el tipo de cada constante y de cada función que definan.
5. THE Archivos_Constantes SHALL usar codificación UTF-8 y declarar `# -*- coding: utf-8 -*-` en la primera línea.

### Requirement 2: Constantes de finanzas_mcp

**User Story:** As a desarrollador de finanzas_mcp, I want las constantes de dominio de finanzas en `finanzas_mcp/constantes.py`, so that monedas, categorías y reglas HITL se consulten en un solo archivo.

#### Acceptance Criteria

1. THE Constantes_Finanzas SHALL definir las monedas válidas `CRC` y `USD` como `frozenset[str]`.
2. THE Constantes_Finanzas SHALL definir la lista cerrada de categorías con los mismos 15 textos y el mismo orden que `CLOSED_CATEGORY_LIST`, como `list[str]`.
3. THE Constantes_Finanzas SHALL definir los modos HITL `siempre` y `adaptativo` como `tuple[str, ...]`.
4. THE Constantes_Finanzas SHALL definir el prefijo de token automático `auto:` como `str`.
5. THE Constantes_Finanzas SHALL definir los códigos de rechazo `AUTOMATIC_TOKEN_NOT_ALLOWED`, `HIGH_AMOUNT_CONFIRMATION_REQUIRED` y `HUMAN_CONFIRMATION_REQUIRED` como `str`.
6. THE Constantes_Finanzas SHALL definir la tupla de campos obligatorios de factura que hoy usa `_CAMPOS_OBLIGATORIOS` en `finanzas_mcp/business/validacion.py`.
7. THE Constantes_Finanzas SHALL importar únicamente módulos de la biblioteca estándar.

### Requirement 3: Constantes de agent

**User Story:** As a desarrollador del agente, I want las constantes del agente en `agent/constantes.py`, so that alertas HITL, prompts y estados del pipeline estén en un solo archivo.

#### Acceptance Criteria

1. THE Constantes_Agent SHALL definir `ALERTAS` con los mismos textos y el mismo orden que `agent/hitl.py`.
2. THE Constantes_Agent SHALL definir `CAMPOS_REQUERIDOS`, `MAX_REGLAS`, `MAX_LONGITUD_REGLA`, `MAX_LONGITUD_RAZON`, `RAZON_SIEMPRE` y `RAZON_LIMPIA` con los valores de `agent/hitl.py`.
3. THE Constantes_Agent SHALL definir `PROMPT_REGISTRAR`, `PROMPT_MONTO_ALTO`, `PROMPT_DUPLICADOS` y `PROMPT_ALERTAS` con los mismos textos de `agent/hitl.py`.
4. THE Constantes_Agent SHALL definir las categorías de contenido sospechoso y `MAX_CARACTERES` (20_000) con los valores de `agent/contenido_sospechoso.py`.
5. THE Constantes_Agent SHALL definir los estados finales del pipeline `success`, `validation_error`, `user_abort`, `step_limit` y `token_limit`.
6. THE Constantes_Agent SHALL definir las razones de terminación del pipeline `success`, `validation_failure`, `step_limit`, `token_limit` y `user_rejection`.
7. THE Constantes_Agent SHALL definir los campos de extracción de `agent/agent.py` (`REQUIRED_FIELDS`, `OPTIONAL_FIELDS`, `ALLOWED_FIELDS` y los campos requeridos de OCR) con los mismos valores.
8. THE Constantes_Agent SHALL exponer `AUTO_TOKEN_PREFIX` importándolo de Constantes_Finanzas, sin redefinir el literal `auto:`.
9. WHEN `agent/agent.py` o `agent/main.py` asignan un estado final o una razón de terminación, THE Backend SHALL usar las constantes de Constantes_Agent en lugar de literales de texto.

### Requirement 4: Constantes de eval

**User Story:** As a investigador que corre el benchmark, I want las constantes de evaluación en `eval/constantes.py`, so that el Golden Set, las métricas y los sistemas evaluados se definan en un solo archivo.

#### Acceptance Criteria

1. THE Constantes_Eval SHALL definir `DIFICULTADES`, `MINIMOS_DIFICULTAD`, `TOTAL_IMAGENES`, `TOTAL_LIMPIA` y `TOTAL_DIFICILES` con los valores de `eval/golden_set.py`.
2. THE Constantes_Eval SHALL definir `TIPOS_CASO`, `SUBTIPOS_INTEGRIDAD`, `VARIANTES_FECHA`, `CONDICIONES_COMPROMISO`, `MINIMO_POR_SUBTIPO_INTEGRIDAD`, `MIN_VECTORES` y `MIN_IMAGENES_POR_VECTOR` con los valores de `eval/golden_set.py`.
3. THE Constantes_Eval SHALL definir `EXTENSIONES`, `CAMPOS_GT` y `CAMPOS_DECIMALES` con los valores de `eval/golden_set.py`.
4. THE Constantes_Eval SHALL definir `TRADUCCION_DIFICULTAD` con las mismas claves y valores de `eval/convertir_labels.py`.
5. THE Constantes_Eval SHALL definir `SISTEMAS` con los nombres `baseline_naive`, `baseline_prompt_guarded` y `arquitectura_mcp` en ese orden.
6. THE Constantes_Eval SHALL definir `VECTORES` con las mismas claves, condiciones de compromiso y textos inyectados de `eval/generar_adversarial.py`.
7. THE Constantes_Eval SHALL definir `CAMPOS_EXACTITUD`, `UMBRALES_MONTO_DEFECTO` y `PARTICIONES` con los valores de `eval/metricas.py`.
8. THE Constantes_Eval SHALL definir `CAMPOS_ACUERDO` con el valor de `eval/anotaciones.py`.
9. WHEN `eval/benchmark.py` necesita la lista de sistemas, THE Backend SHALL exponer `SISTEMAS_VALIDOS` como alias del mismo objeto que `SISTEMAS` de Constantes_Eval.
10. THE Constantes_Eval SHALL omitir cualquier importación de `finanzas_mcp`, `agent` y `baseline`.

### Requirement 5: Constantes independientes de baseline

**User Story:** As a mantenedor de baseline, I want `baseline/constantes.py` independiente del resto del Backend, so that los baselines cumplan la restricción de aislamiento del Req. 10.10.

#### Acceptance Criteria

1. THE Constantes_Baseline SHALL definir `ESTADOS_FINALES` con los textos `registrada`, `rechazada`, `usuario_rechazo`, `limite` y `error` en ese orden.
2. THE Constantes_Baseline SHALL definir `CAMPOS` con los siete campos de la traza común en el orden de `baseline/traza_comun.py`.
3. THE Constantes_Baseline SHALL definir el nombre de herramienta `insertar_transaccion`.
4. THE Constantes_Baseline SHALL definir los nombres de sistema `baseline_naive`, `baseline_prompt_guarded` y `arquitectura_mcp`.
5. THE Constantes_Baseline SHALL definir la tabla que traduce cada estado del pipeline (`success`, `validation_error`, `user_abort`, `step_limit`, `token_limit`) a su estado final de baseline, con los textos escritos en el propio archivo.
6. THE Constantes_Baseline SHALL omitir importaciones de `finanzas_mcp`, `ocr_mcp`, `agent`, `api_pruebas`, `mcp` y `eval`.
7. THE Backend SHALL omitir cualquier importación de `Constantes_Eval` desde `baseline/`, y de `Constantes_Baseline` como fuente de valores de `eval/`.

### Requirement 6: Compatibilidad con nombres antiguos

**User Story:** As a desarrollador, I want que los módulos actuales conserven sus nombres antiguos, so that los imports y las pruebas existentes sigan funcionando.

#### Acceptance Criteria

1. THE Backend SHALL conservar en cada Modulo_Origen el Alias_Compatible de cada constante movida, incluidos `CLOSED_CATEGORY_LIST`, `MODOS_HITL`, `ALERTAS`, `ESTADOS_FINALES`, `DIFICULTADES`, `TIPOS_CASO`, `SUBTIPOS_INTEGRIDAD`, `CONDICIONES_COMPROMISO`, `SISTEMAS` y `VECTORES`.
2. WHEN un módulo importa un Alias_Compatible, THE Backend SHALL entregar el mismo objeto (`is`) que el Archivo_Constantes del paquete.
3. THE Backend SHALL conservar `agent.hitl.AUTO_TOKEN_PREFIX` y `finanzas_mcp.business.hitl.AUTO_TOKEN_PREFIX` apuntando al mismo `str` definido en Constantes_Finanzas.
4. THE Backend SHALL definir el literal `auto:` en un único archivo: Constantes_Finanzas.
5. THE Backend SHALL conservar sin modificar los archivos de `tests/` existentes.

### Requirement 7: Artefactos generados sin cambios

**User Story:** As a investigador, I want que los artefactos generados no cambien, so that los resultados del paper sigan siendo reproducibles.

#### Acceptance Criteria

1. THE Backend SHALL conservar sin cambios los textos, el orden y el tipo de cada constante movida.
2. THE Backend SHALL conservar sin cambios `eval/labels.csv`, `eval/golden_set/adversarial_security/adversarial_manifest.json` y `politica.json`.
3. THE Backend SHALL generar el manifiesto adversarial con el mismo contenido que antes del cambio.

### Requirement 8: Prueba de valores y alias

**User Story:** As a mantenedor, I want una prueba que fije los valores y los alias, so that una regresión futura se detecte de inmediato.

#### Acceptance Criteria

1. THE Prueba_Constantes SHALL comparar cada constante de los Archivos_Constantes con su Valor_Original escrito como literal en la prueba.
2. THE Prueba_Constantes SHALL verificar, para cada fila de la Tabla_Alias, que el atributo antiguo del Modulo_Origen es el mismo objeto (`is`) que la constante nueva.
3. THE Prueba_Constantes SHALL verificar mediante análisis AST que `baseline/*.py` omite importaciones de `finanzas_mcp`, `ocr_mcp`, `agent`, `api_pruebas`, `mcp` y `eval`.
4. THE Prueba_Constantes SHALL verificar mediante análisis AST que `finanzas_mcp/constantes.py` omite importaciones de `mcp`.
5. THE Prueba_Constantes SHALL verificar mediante análisis AST que el literal `auto:` se asigna en un único archivo del Backend.
6. THE Prueba_Constantes SHALL verificar mediante análisis AST que cada función definida en los Archivos_Constantes tiene anotaciones de tipo en parámetros y retorno.
7. IF una constante o un alias difiere de lo esperado, THEN THE Prueba_Constantes SHALL fallar con un mensaje que indique el módulo y el nombre afectados.

### Requirement 9: Validación con la suite completa

**User Story:** As a mantenedor, I want validar la suite completa al final, so that confirme que el cambio no rompe nada.

#### Acceptance Criteria

1. WHEN termina la última tarea de implementación, THE Suite_Completa SHALL terminar con al menos 234 pruebas aprobadas y 2 omitidas, más las pruebas nuevas de la Prueba_Constantes.
2. IF la Suite_Completa reporta un fallo, THEN THE Backend SHALL corregirse hasta que la Suite_Completa pase sin modificar pruebas existentes.
