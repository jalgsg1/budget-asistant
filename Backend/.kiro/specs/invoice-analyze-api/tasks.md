# Implementation Plan: invoice-analyze-api

## Overview

Implementación en Python de `POST /facturas/analizar` en `Backend/api_pruebas`. Primero se crea el modelo `Transaction` y el esquema de respuesta. Después se refactoriza la validación de archivos y se agrega `analizar_subida` en `ServiciosNegocio`. Por último se crea la ruta, se registra en `app.py` y se elimina `POST /validar`. Las pruebas van en `Backend/tests/` y usan Hypothesis y `TestClient` con el extractor falso de `tests/_dobles.py`.

## Tasks

- [x] 1. Crear el paquete `Backend/model`
  - [x] 1.1 Implementar el dataclass `Transaction`
    - Crear `Backend/model/__init__.py` (exporta `Transaction`) y `Backend/model/transaction.py`
    - Definir `COLUMNAS`, los campos obligatorios y opcionales (`id`, `subtotal`, `iva`, `descripcion` opcionales; campos con valor por defecto al final)
    - Implementar `from_row` (acepta `sqlite3.Row`/`dict` por nombre o tupla en el orden de `COLUMNAS`; lanza `KeyError`/`ValueError` si falta una columna obligatoria) y `to_dict`
    - Importar solo `dataclasses` y `typing`, sin `mcp` ni `finanzas_mcp`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 1.2 Write property test for round trip fila-modelo
    - Archivo `Backend/tests/test_model_transaction.py`
    - **Property 12: Round trip fila-modelo**
    - **Validates: Requirements 8.5**

  - [x]* 1.3 Write unit tests for Transaction
    - Archivo `Backend/tests/test_model_transaction_unit.py`
    - Comparar los campos con `PRAGMA table_info(transactions)` y verificar la opcionalidad de 8.3
    - Importar `model` en un subproceso limpio y verificar que `mcp` y `finanzas_mcp` no están en `sys.modules`
    - Verificar que `test_estructura_repositorio.py` no falla con la carpeta nueva
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 2. Implementar el análisis en `ServiciosNegocio`
  - [x] 2.1 Agregar el esquema `AnalisisFacturaRespuesta`
    - En `api_pruebas/esquemas.py` agregar `AnalisisFacturaRespuesta` con `campos`, `campos_no_identificados`, `validacion` y `advertencias`, reutilizando `ValidacionRespuesta` y `ReglaResultado`
    - _Requirements: 1.4, 2.1, 2.2, 3.1, 4.1_

  - [x] 2.2 Extraer `_validar_archivo` de `ocr_subida`
    - En `api_pruebas/servicios.py` crear `_validar_archivo(nombre, contenido) -> str` con las comprobaciones de extensión, firma y tamaño
    - Hacer que `ocr_subida` lo use sin cambiar sus errores 415/413
    - _Requirements: 4.5, 7.4_

  - [x] 2.3 Implementar las funciones de apoyo
    - Agregar `CAMPOS_FACTURA` y `CAMPOS_OBLIGATORIOS`
    - `_repartir_campos(payload)`: partición en `campos` y `campos_no_identificados` en el orden de `CAMPOS_FACTURA`, ignora claves ajenas, trata cadenas en blanco como vacías y canonicaliza `categoria` contra `CLOSED_CATEGORY_LIST`
    - `_reglas_validacion(campos, no_identificados)`: llama a `evaluar_factura`, agrega la regla R1 fallida (`MISSING_FIELDS`) si falta un Campo_Obligatorio y R1 no figura, y redacta los mensajes con `redactar`
    - `_advertencias(ocr, umbral)`: advertencia de baja confianza (`confianza_ocr` o `confidence` contra `config.policy.umbral_confianza_ocr`) y de contenido sospechoso (`escanear`), con texto redactado
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3_

  - [x] 2.4 Implementar `ServiciosNegocio.analizar_subida`
    - Llamar a `_validar_archivo` y convertir `ErrorApi` en análisis de fallo con HTTP 200
    - Escribir el contenido en un archivo temporal con `tempfile.mkstemp(suffix=ext)`, llamar al extractor y borrarlo en `finally` (un fallo al borrar se registra en el log)
    - Manejar excepciones del extractor, `OcrToolError` y JSON ilegible con el mensaje `Fallo en la extracción OCR (<Tipo>).` redactado
    - Construir la respuesta con `_repartir_campos`, `_reglas_validacion` y `_advertencias`; en los fallos usar `campos = {}` para que los ocho campos queden en `campos_no_identificados`
    - No usar `TransactionRepository`, `TrazaStore`, `batch` ni `INVOICES_DIR`
    - _Requirements: 1.2, 1.3, 3.2, 3.3, 4.4, 4.5, 5.2, 6.1, 6.2, 6.3_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Exponer la ruta, eliminar `/validar` y probar
  - [x] 4.1 Crear `api_pruebas/rutas/facturas.py`
    - Definir `POST /facturas/analizar` con `archivo: UploadFile = File(...)`, `response_model=AnalisisFacturaRespuesta` y respuesta 422 documentada con `ErrorEstandar`
    - Leer como máximo `max_upload_bytes + 1` bytes y delegar en `servicios.analizar_subida`
    - _Requirements: 1.1, 1.3, 1.4, 5.1_

  - [x] 4.2 Registrar la ruta nueva y eliminar `POST /validar`
    - En `app.py` importar `facturas` y registrarlo en lugar de `factura`
    - Borrar `api_pruebas/rutas/factura.py` y el esquema `FacturaIn` de `esquemas.py`
    - Conservar `ServiciosNegocio.validar`, `ReglaResultado` y `ValidacionRespuesta`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 4.3 Actualizar referencias residuales
    - Buscar `/validar`, `FacturaIn` y `rutas/factura` en `README.md`, pruebas y documentación, y actualizarlos
    - Verificar que el `Dockerfile` y `.dockerignore` incluyan `Backend/model`
    - _Requirements: 7.5, 8.1_

  - [x]* 4.4 Write property test for partición de campos
    - Archivo `Backend/tests/test_analizar_prop_01.py`
    - **Property 1: Partición de campos**
    - **Validates: Requirements 1.2, 2.1, 2.2, 2.3**

  - [x]* 4.5 Write property test for categoría fuera de la lista cerrada
    - Archivo `Backend/tests/test_analizar_prop_02.py`
    - **Property 2: Categoría fuera de la lista cerrada**
    - **Validates: Requirements 2.4**

  - [x]* 4.6 Write property test for forma de la respuesta
    - Archivo `Backend/tests/test_analizar_prop_03.py`
    - **Property 3: Forma de la respuesta de análisis**
    - **Validates: Requirements 1.3, 3.1, 4.1**

  - [x]* 4.7 Write property test for validación contra evaluar_factura
    - Archivo `Backend/tests/test_analizar_prop_04.py`
    - **Property 4: La validación refleja a evaluar_factura**
    - **Validates: Requirements 3.2**

  - [x]* 4.8 Write property test for campo obligatorio faltante
    - Archivo `Backend/tests/test_analizar_prop_05.py`
    - **Property 5: Campo obligatorio faltante invalida con R1**
    - **Validates: Requirements 3.3**

  - [x]* 4.9 Write property test for redacción de secretos
    - Archivo `Backend/tests/test_analizar_prop_06.py`
    - **Property 6: Redacción de secretos**
    - **Validates: Requirements 3.4, 4.4, 4.5**

  - [x]* 4.10 Write property test for advertencia de baja confianza
    - Archivo `Backend/tests/test_analizar_prop_07.py`
    - **Property 7: Advertencia de baja confianza**
    - **Validates: Requirements 4.2**

  - [x]* 4.11 Write property test for advertencia de contenido sospechoso
    - Archivo `Backend/tests/test_analizar_prop_08.py`
    - **Property 8: Advertencia de contenido sospechoso**
    - **Validates: Requirements 4.3**

  - [x]* 4.12 Write property test for respuesta de fallo uniforme
    - Archivo `Backend/tests/test_analizar_prop_09.py`
    - **Property 9: Respuesta de fallo uniforme**
    - **Validates: Requirements 4.4, 4.5**

  - [x]* 4.13 Write property test for archivos temporales residuales
    - Archivo `Backend/tests/test_analizar_prop_10.py`
    - **Property 10: Sin archivos temporales residuales**
    - **Validates: Requirements 5.2**

  - [x]* 4.14 Write property test for análisis sin efectos secundarios
    - Archivo `Backend/tests/test_analizar_prop_11.py`
    - **Property 11: Análisis sin efectos secundarios**
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [x]* 4.15 Write example and smoke tests for the endpoint
    - Archivo `Backend/tests/test_api_facturas_analizar.py`
    - PNG mínimo devuelve 200 con las cuatro claves; sin parte `archivo` devuelve 422 `VALIDATION_ERROR`
    - `/openapi.json` contiene `/facturas/analizar` con `AnalisisFacturaRespuesta` y no contiene `/validar`
    - `POST /validar` devuelve 404 con `{code, message}`
    - Siguen registradas `/ocr`, `/transacciones`, `/pipeline`, `/batch` y `/trazas`; no existen `rutas/factura.py` ni `FacturaIn`
    - Regresión de `/ocr` (`test_api_ocr_form.py`, `test_api_pruebas_hitl.py`) tras extraer `_validar_archivo`
    - _Requirements: 1.1, 1.4, 5.1, 7.1, 7.2, 7.4, 7.5_

- [x] 5. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Hypothesis, mínimo 100 iteraciones, etiqueta `Feature: invoice-analyze-api, Property N`)
- Unit tests validate specific examples and edge cases

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.3"] },
    { "id": 2, "tasks": ["2.4"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2"] },
    { "id": 5, "tasks": ["4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9", "4.10", "4.11", "4.12", "4.13", "4.14", "4.15"] }
  ]
}
```
