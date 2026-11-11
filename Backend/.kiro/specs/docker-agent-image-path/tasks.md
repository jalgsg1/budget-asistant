# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - CLI sin image_path no falla en argparse
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to the concrete failing case: `main(argv=[])` (sin `image_path`) con stdin TTY y no TTY, y con entrada vacía/EOF en el prompt
  - Crear la prueba en `Backend/tests/` con `pytest` y `hypothesis`, parcheando `McpToolbox`/`run_cli` para no iniciar servidores MCP
  - Bug Condition (isBugCondition): `input.image_path IS NULL AND NOT containsPositionalImagePath(input.argv)`
  - Afirmar expectedBehavior: (se pidió la ruta y se procesó con la ruta ingresada) OR (se mostró el uso con `docker compose run`, código de salida != 0 y sin traza ni `SystemExit` de argparse)
  - Ejecutar la prueba en código SIN corregir
  - **EXPECTED OUTCOME**: Test FAILS (esto es correcto - prueba que el bug existe)
  - Documentar contraejemplos (por ejemplo, `main(argv=[])` lanza `SystemExit(2)` con "the following arguments are required: image_path")
  - Marcar la tarea completa cuando la prueba esté escrita, ejecutada y el fallo documentado
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Invocaciones con image_path
  - **IMPORTANT**: Follow observation-first methodology
  - Observar en código SIN corregir: `main(argv=[ruta])` pasa `ruta` a `run_cli` y devuelve el código de `_EXIT_CODES` para cada `status` (`success`=0, `validation_error`=1, `user_abort`=2, `step_limit`/`token_limit`=3)
  - Observar: `main(image_path=ruta)` usa `ruta` sin leer stdin
  - Escribir pruebas basadas en propiedades: para cualquier ruta no vacía y cualquier estado de TTY, `main(argv=[ruta])` invoca el pipeline con exactamente `ruta`, nunca pregunta y conserva el código de salida del mapa
  - Escribir prueba sobre `docker-compose.yml`: los servicios `finanzas-mcp`, `ocr-mcp`, `api-pruebas`, volúmenes `./data`, `./facturas`, `./traces` y variables `DB_PATH`, `INVOICES_DIR`, `TRACES_DIR`, `MCP_USER_ID` permanecen iguales
  - Ejecutar las pruebas en código SIN corregir
  - **EXPECTED OUTCOME**: Tests PASS (confirma el comportamiento base a preservar)
  - Marcar la tarea completa cuando las pruebas estén escritas, ejecutadas y pasando en código sin corregir
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix para image_path faltante en el CLI del agente

  - [x] 3.1 Implement the fix
    - En `Backend/agent/main.py`, cambiar a `parser.add_argument("image_path", nargs="?", default=None, ...)`
    - Agregar constantes `USAGE_DOCKER` (ejemplo `docker compose run --rm gestor-facturas python -m agent.main /app/facturas/mi_factura.jpg`) y `EXIT_USAGE = 64` fuera de `_EXIT_CODES`
    - Agregar helper privado `_resolve_image_path(image_path, stdin, stdout)`: devuelve la ruta si existe; si `stdin.isatty()` usa `ConsoleIO.ask("Ruta de la imagen de la factura (ej. /app/facturas/mi_factura.jpg):")` con `strip()`; devuelve `None` si no es TTY o la entrada es vacía/EOF
    - En `main`, resolver la ruta antes de cargar política y levantar `McpToolbox`; si es `None`, imprimir `USAGE_DOCKER` a stderr y devolver `EXIT_USAGE` sin traza
    - Opcional: agregar comentario en el servicio `gestor-facturas` de `Backend/docker-compose.yml` sobre el prompt y el uso de `docker compose run`/`attach`, sin cambiar `command`, volúmenes ni variables
    - _Bug_Condition: isBugCondition(input) where input.image_path IS NULL AND NOT containsPositionalImagePath(input.argv)_
    - _Expected_Behavior: expectedBehavior(result) from design_
    - _Preservation: Preservation Requirements from design_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - CLI sin image_path no falla en argparse
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - Ejecutar la prueba de exploración de la tarea 1
    - **EXPECTED OUTCOME**: Test PASSES (confirma que el bug está corregido)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Invocaciones con image_path
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Ejecutar las pruebas de preservación de la tarea 2
    - **EXPECTED OUTCOME**: Tests PASS (confirma que no hay regresiones)
    - Confirmar que todas las pruebas siguen pasando tras el fix
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3"] },
    { "id": 3, "tasks": ["4"] }
  ]
}
```
