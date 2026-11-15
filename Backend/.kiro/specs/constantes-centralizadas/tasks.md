# Implementation Plan: constantes-centralizadas

## Overview

Se crea un `constantes.py` por paquete (`finanzas_mcp`, `agent`, `eval`, `baseline`) y se redirigen los módulos actuales para que importen de ahí, conservando los nombres antiguos como alias del mismo objeto. Los valores no cambian. Al final se agrega `tests/test_constantes.py` y se corre la suite completa. Lenguaje: Python. No se modifican las pruebas existentes.

## Tasks

- [x] 1. Centralizar constantes de finanzas_mcp
  - [x] 1.1 Crear `finanzas_mcp/constantes.py` y redirigir los módulos de negocio
    - Crear el archivo con `# -*- coding: utf-8 -*-`, solo biblioteca estándar y sin importar `mcp`.
    - Definir `MONEDAS_VALIDAS` (frozenset CRC/USD), `CAMPOS_OBLIGATORIOS`, `CATEGORIAS_CERRADAS` (list, mismos 15 textos y orden), `MODOS_HITL`, `AUTO_TOKEN_PREFIX`, `CODIGO_AUTO_NO_PERMITIDO`, `CODIGO_MONTO_ALTO` y `CODIGO_HUMANO`, con type hints.
    - En `business/categorias.py`: `CLOSED_CATEGORY_LIST = CATEGORIAS_CERRADAS` (mismo objeto).
    - En `business/hitl.py`: importar `MODOS_HITL`, `AUTO_TOKEN_PREFIX` y los tres códigos; conservar sus nombres actuales.
    - En `business/validacion.py`: `_MONEDAS_VALIDAS` y `_CAMPOS_OBLIGATORIOS` como alias de las constantes nuevas.
    - Confirmar que `server.py`, `transacciones.py` y `finanzas_mcp/business/__init__.py` siguen importando sin cambios.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 6.1, 6.2, 6.3, 7.1_

- [x] 2. Centralizar constantes de agent
  - [x] 2.1 Crear `agent/constantes.py` y redirigir `agent/hitl.py` y `agent/contenido_sospechoso.py`
    - Definir `ALERTAS`, `CAMPOS_REQUERIDOS`, `MAX_REGLAS`, `MAX_LONGITUD_REGLA`, `MAX_LONGITUD_RAZON`, `RAZON_SIEMPRE`, `RAZON_LIMPIA`, `PROMPT_REGISTRAR`, `PROMPT_MONTO_ALTO`, `PROMPT_DUPLICADOS`, `PROMPT_ALERTAS`, `CATEGORIAS_CONTENIDO_SOSPECHOSO` y `MAX_CARACTERES` (20_000) con los textos actuales.
    - Definir `ESTADO_EXITO`, `ESTADO_ERROR_VALIDACION`, `ESTADO_ABORTO_USUARIO`, `ESTADO_LIMITE_PASOS`, `ESTADO_LIMITE_TOKENS`, `ESTADOS_PIPELINE`, y las `RAZON_*` con `RAZONES_PIPELINE`.
    - Definir `REQUIRED_FIELDS`, `OPTIONAL_FIELDS`, `ALLOWED_FIELDS` y `OCR_REQUIRED_FIELDS`.
    - Importar `AUTO_TOKEN_PREFIX` de `finanzas_mcp.constantes`; no escribir el literal `auto:`.
    - En `agent/hitl.py`: importar las constantes y conservar `ALERTAS`, `AUTO_TOKEN_PREFIX`, `CAMPOS_REQUERIDOS`, `PROMPT_*`, `RAZON_*`, `MAX_*`. Eliminar la definición duplicada de `AUTO_TOKEN_PREFIX`.
    - En `agent/contenido_sospechoso.py`: `CATEGORIAS = CATEGORIAS_CONTENIDO_SOSPECHOSO` y `MAX_CARACTERES` importado.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 6.1, 6.2, 6.3, 6.4, 7.1_

  - [x] 2.2 Usar las constantes de estado y razón en `agent/agent.py`, `agent/main.py` y `agent/tracer.py`
    - Reemplazar los literales `success`, `validation_error`, `user_abort`, `step_limit`, `token_limit`, `validation_failure` y `user_rejection` por `ESTADO_*` y `RAZON_*`.
    - Mantener `REQUIRED_FIELDS`, `OPTIONAL_FIELDS`, `ALLOWED_FIELDS` y `_OCR_REQUIRED` como alias en `agent/agent.py`.
    - Construir `_EXIT_CODES` en `main.py` con las constantes `ESTADO_*` como claves y los mismos códigos numéricos.
    - Usar `ESTADO_EXITO` como valor por defecto de `Trace.final_status` en `tracer.py`.
    - No cambiar los valores de las claves `step_limit` y `token_limit` de `politica.json` ni de `Policy`: son nombres de campo, no estados.
    - _Requirements: 3.9, 6.1, 6.2, 7.1_

- [x] 3. Centralizar constantes de eval
  - [x] 3.1 Crear `eval/constantes.py` y redirigir `golden_set.py`, `convertir_labels.py`, `metricas.py` y `anotaciones.py`
    - Crear el archivo con solo biblioteca estándar (sin importar `finanzas_mcp`, `agent` ni `baseline`).
    - Definir `TOTAL_IMAGENES`, `TOTAL_LIMPIA`, `TOTAL_DIFICILES`, `MINIMOS_DIFICULTAD`, `DIFICULTADES`, `EXTENSIONES`, `CAMPOS_GT`, `CAMPOS_DECIMALES`, `TIPOS_CASO`, `SUBTIPOS_INTEGRIDAD`, `MINIMO_POR_SUBTIPO_INTEGRIDAD`, `VARIANTES_FECHA`, `CONDICIONES_COMPROMISO`, `MIN_VECTORES`, `MIN_IMAGENES_POR_VECTOR`, `TRADUCCION_DIFICULTAD`, `SISTEMAS`, `CAMPOS_EXACTITUD`, `UMBRALES_MONTO_DEFECTO`, `PARTICIONES` y `CAMPOS_ACUERDO`.
    - Construir `DIFICULTADES` con `("limpia",) + tuple(MINIMOS_DIFICULTAD)` para conservar el orden.
    - En cada módulo origen importar la constante y conservar el nombre antiguo.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 4.8, 4.10, 6.1, 6.2, 7.1_

  - [x] 3.2 Redirigir `eval/runner.py`, `eval/benchmark.py` y `eval/generar_adversarial.py`
    - Agregar `VECTORES` a `eval/constantes.py` copiando el diccionario completo (claves, condiciones y textos inyectados) sin cambios.
    - En `eval/generar_adversarial.py` importar `VECTORES`; el manifiesto generado debe quedar idéntico.
    - En `eval/runner.py` importar `SISTEMAS`.
    - En `eval/benchmark.py` usar `from eval.constantes import SISTEMAS as SISTEMAS_VALIDOS`.
    - No modificar `eval/labels.csv` ni `eval/golden_set/adversarial_security/adversarial_manifest.json`.
    - _Requirements: 4.5, 4.6, 4.9, 6.1, 6.2, 7.1, 7.2, 7.3_

- [x] 4. Centralizar constantes de baseline
  - [x] 4.1 Crear `baseline/constantes.py` independiente y redirigir los módulos de baseline
    - Crear el archivo sin ningún import de `finanzas_mcp`, `ocr_mcp`, `agent`, `api_pruebas`, `mcp` ni `eval`; escribir los textos de nuevo.
    - Definir `ESTADOS_FINALES`, `CAMPOS`, `HERRAMIENTA_INSERTAR_NOMBRE`, `SISTEMA_NAIVE`, `SISTEMA_PROMPT_GUARDED`, `SISTEMA_ARQUITECTURA` y `ESTADO_AGENTE_A_FINAL`.
    - En `traza_comun.py`: conservar `ESTADOS_FINALES`, `CAMPOS` y `_ESTADO_AGENTE` como alias; usar `SISTEMA_ARQUITECTURA` en lugar del literal.
    - En `_comun.py`: usar `HERRAMIENTA_INSERTAR_NOMBRE` para `HERRAMIENTA_INSERTAR["name"]` y para la comparación de `c.get("nombre")`.
    - En `baseline_naive.py` y `baseline_prompt_guarded.py`: `NOMBRE = SISTEMA_NAIVE` y `NOMBRE = SISTEMA_PROMPT_GUARDED`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.1, 6.2, 7.1_

- [x] 5. Prueba `tests/test_constantes.py`
  - [x] 5.1 Crear el archivo de prueba con la existencia de los archivos y los valores originales
    - Crear `tests/test_constantes.py` con `# -*- coding: utf-8 -*-`, `unittest`, type hints en las funciones auxiliares.
    - Probar que existen los cuatro `constantes.py`.
    - Congelar `VALORES_ORIGINALES` como literales copiados del código previo al cambio (categorías, alertas, `VECTORES`, `TRADUCCION_DIFICULTAD`, etc.) y comparar valor y tipo con `subTest`.
    - Omitir con `unittest.skipUnless` lo que requiera Pillow (`eval.generar_adversarial`) si no está instalado.
    - **Property 1: Valores idénticos a los originales**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 7.1, 8.1, 8.7**

  - [x] 5.2 Agregar la prueba de alias del mismo objeto
    - Definir `TABLA_ALIAS` con todas las filas (módulo antiguo, nombre antiguo, módulo de constantes, nombre nuevo), incluidos `CLOSED_CATEGORY_LIST`, `MODOS_HITL`, `ALERTAS`, `ESTADOS_FINALES`, `DIFICULTADES`, `TIPOS_CASO`, `SUBTIPOS_INTEGRIDAD`, `CONDICIONES_COMPROMISO`, `SISTEMAS`, `SISTEMAS_VALIDOS`, `VECTORES` y `AUTO_TOKEN_PREFIX` (en `agent.hitl` y `finanzas_mcp.business.hitl`).
    - Verificar `getattr(antiguo, n) is getattr(constantes, m)` con mensaje `modulo.nombre`.
    - **Property 2: Los alias antiguos referencian el mismo objeto**
    - **Validates: Requirements 3.8, 4.9, 6.1, 6.2, 6.3, 8.2, 8.7**

  - [x] 5.3 Agregar las pruebas AST de aislamiento de dependencias
    - Verificar que ningún `baseline/*.py` importa `finanzas_mcp`, `ocr_mcp`, `agent`, `api_pruebas`, `mcp` ni `eval`.
    - Verificar que `finanzas_mcp/constantes.py` no importa `mcp`, y que `eval/constantes.py` no importa `finanzas_mcp`, `agent` ni `baseline`.
    - **Property 3: Aislamiento de dependencias**
    - **Validates: Requirements 2.7, 4.10, 5.6, 5.7, 8.3, 8.4**

  - [x] 5.4 Agregar la prueba de definición única de `AUTO_TOKEN_PREFIX`
    - Con AST, recorrer los `.py` del Backend fuera de `tests/`, `.venv` y `.hypothesis`, y verificar que el literal `"auto:"` solo se asigna en `finanzas_mcp/constantes.py`.
    - **Property 4: Definición única de AUTO_TOKEN_PREFIX**
    - **Validates: Requirements 3.8, 6.4, 8.5**

  - [x] 5.5 Agregar la prueba de type hints y encoding en los archivos de constantes
    - Con AST, verificar anotaciones en parámetros y retorno de toda función definida en los cuatro `constantes.py`, y `encoding="utf-8"` en cualquier apertura de archivo.
    - **Property 5: Tipos anotados en los Archivos_Constantes**
    - **Validates: Requirements 1.4, 1.5, 8.6**

- [x] 6. Checkpoint final - Suite completa
  - Desde `Backend`, ejecutar `python -m pytest tests -q`.
  - Esperado: al menos 234 passed y 2 skipped, más las pruebas nuevas de `tests/test_constantes.py`.
  - Verificar que `git status` no muestra cambios en `tests/` salvo el archivo nuevo, ni en `eval/labels.csv`, el manifiesto adversarial y `politica.json`.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 6.5, 7.2, 9.1, 9.2_

## Notes

- Ninguna sub-tarea es opcional: el usuario pidió explícitamente la prueba `tests/test_constantes.py`.
- Las propiedades se implementan como pruebas parametrizadas con `unittest.subTest`, no con Hypothesis (dominio finito y determinista).
- `baseline/constantes.py` duplica a propósito nombres de sistema y estados del pipeline; la prueba 5.1 detecta cualquier desvío frente a `eval` y `agent`.
- Este flujo solo produce el spec. La implementación se ejecuta abriendo este archivo y pulsando "Start task".

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "4.1"] },
    { "id": 1, "tasks": ["2.1", "3.2"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["5.3"] },
    { "id": 6, "tasks": ["5.4"] },
    { "id": 7, "tasks": ["5.5"] }
  ]
}
```
