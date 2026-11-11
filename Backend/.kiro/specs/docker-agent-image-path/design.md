# docker-agent-image-path Bugfix Design

## Overview

Al ejecutar `docker compose up --build`, el servicio `gestor-facturas` lanza `python -m agent.main` (CMD del Dockerfile) sin argumentos. En `agent/main.py`, `main()` declara `image_path` como argumento posicional obligatorio de argparse, por lo que el proceso termina de inmediato con `the following arguments are required: image_path`, aunque el servicio tiene `stdin_open` y `tty` habilitados.

La estrategia de fix es mínima y localizada en `main()`: hacer `image_path` opcional en el parser (`nargs="?"`). Si falta, se resuelve así:
- stdin es TTY: se pide la ruta con un prompt y se continúa el procesamiento.
- stdin no es TTY, o la entrada queda vacía/EOF: se imprime un mensaje de uso con ejemplo de Docker y se devuelve un código distinto de cero, sin traza.

No se modifican el pipeline, los servidores MCP, los códigos de salida existentes ni los demás servicios de Compose.

## Glossary

- **Bug_Condition (C)**: El CLI se inicia sin `image_path` (ni por parámetro ni en `argv`). Hoy provoca el error de argparse.
- **Property (P)**: Sin `image_path`, el CLI pide la ruta si hay TTY, o muestra un uso claro y sale con código distinto de cero sin traza.
- **Preservation**: Comportamiento cuando `image_path` sí se proporciona, códigos de salida existentes, servicios `finanzas-mcp`, `ocr-mcp`, `api-pruebas` y volúmenes/variables de entorno.
- **main**: Función en `Backend/agent/main.py` que es el punto de entrada del CLI y devuelve el código de salida.
- **ConsoleIO**: Clase en `Backend/agent/main.py` que implementa `UserIO` sobre stdin/stdout.
- **_EXIT_CODES**: Mapa de `status` a código de salida (`success`=0, `validation_error`=1, `user_abort`=2, `step_limit`/`token_limit`=3).
- **gestor-facturas**: Servicio de `Backend/docker-compose.yml` con `stdin_open: true` y `tty: true` que usa el CMD por defecto.

## Bug Details

### Bug Condition

El bug se manifiesta cuando el CLI arranca sin ruta de imagen, caso típico del servicio `gestor-facturas` con `docker compose up`. El parser define `image_path` como posicional obligatorio, así que argparse aborta con `SystemExit(2)` antes de que exista oportunidad de preguntar la ruta o de mostrar un uso adaptado a Docker.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type CliInvocation { image_path: string | null, argv: list<string>, stdin_is_tty: boolean }
  OUTPUT: boolean

  RETURN input.image_path IS NULL
         AND NOT containsPositionalImagePath(input.argv)
END FUNCTION
```

### Examples

- `docker compose up --build` (TTY habilitado): actual, error de argparse y salida 2. Esperado, prompt "Ruta de la imagen" y procesamiento con la ruta ingresada.
- `docker compose run --rm -T gestor-facturas` (sin TTY): actual, error de argparse. Esperado, mensaje de uso con ejemplo `docker compose run --rm gestor-facturas python -m agent.main /app/facturas/mi_factura.jpg` y código distinto de cero sin traza.
- TTY y el usuario pulsa Enter con la ruta vacía o Ctrl+D (EOF): actual, no aplica (nunca se llega al prompt). Esperado, mensaje de uso y código distinto de cero.
- `python -m agent.main /app/facturas/mi_factura.jpg` (no es bug): se procesa igual que antes.
- `main(image_path="x.jpg")` programático (no es bug): usa `x.jpg` sin preguntar.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Con `image_path` en `argv` o por parámetro, el pipeline procesa y registra igual que antes, con los mismos códigos de salida.
- `main(image_path=...)` no vuelve a pedir la ruta.
- Los servicios `finanzas-mcp`, `ocr-mcp` y `api-pruebas` con sus perfiles conservan su `command` y configuración.
- Volúmenes `./data`, `./facturas`, `./traces` y variables `DB_PATH`, `INVOICES_DIR`, `TRACES_DIR`, `MCP_USER_ID` no cambian.

**Scope:**
Toda invocación que ya incluye `image_path` queda fuera del fix. También quedan intactos:
- Los argumentos `-h/--help` de argparse.
- La carga de política, SKILL.md y el arranque de `McpToolbox`.
- Los mensajes de resultado impresos al final.

## Hypothesized Root Cause

1. **Argumento posicional obligatorio**: `parser.add_argument("image_path", ...)` sin `nargs="?"` hace que argparse falle antes de cualquier lógica de la aplicación. Es la causa principal y está confirmada en el código.
2. **Sin fallback interactivo**: `main()` no consulta `sys.stdin.isatty()` ni usa `ConsoleIO.ask` para obtener la ruta, aunque el servicio Compose habilita `stdin_open`/`tty`.
3. **Sin mensaje de uso para Docker**: argparse solo muestra su uso genérico. No hay un mensaje con el ejemplo de `docker compose run`.
4. **CMD sin argumentos en Dockerfile/Compose**: el servicio `gestor-facturas` no define `command`, por lo que depende del CMD por defecto. Es un factor contribuyente, no la causa. Se corrige en el CLI en lugar de fijar una ruta en Compose.

## Correctness Properties

Property 1: Bug Condition - CLI sin image_path no falla en argparse

_For any_ invocación donde la condición del bug se cumple (isBugCondition devuelve true), la función `main` corregida SHALL: si stdin es TTY, pedir la ruta con un prompt y procesar con la ruta ingresada no vacía; si stdin no es TTY, o la ruta ingresada es vacía o llega EOF, imprimir un mensaje de uso con un ejemplo de invocación en Docker y devolver un código de salida distinto de cero, sin traza de error y sin error de argparse por `image_path` faltante.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Invocaciones con image_path

_For any_ invocación donde la condición del bug NO se cumple (isBugCondition devuelve false), la función `main` corregida SHALL producir el mismo resultado que la original, usando la ruta dada sin preguntar y conservando los códigos de salida (`success`=0, `validation_error`=1, `user_abort`=2, `step_limit`/`token_limit`=3), así como la configuración de los demás servicios, volúmenes y variables de entorno.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Asumiendo que el análisis de causa raíz es correcto:

**File**: `Backend/agent/main.py`

**Function**: `main`

**Specific Changes**:
1. **Posicional opcional**: `parser.add_argument("image_path", nargs="?", default=None, ...)`. Con ello `argv` que incluye la ruta se comporta igual que antes.
2. **Helper `_resolve_image_path(image_path, stdin, stdout)`** (nueva función privada):
   - Si hay ruta, la devuelve sin cambios.
   - Si `stdin.isatty()` es true, usa `ConsoleIO(stdin, stdout).ask("Ruta de la imagen de la factura (ej. /app/facturas/mi_factura.jpg):")` y hace `strip()`.
   - Si no es TTY, o el resultado es `None`/vacío, devuelve `None`.
3. **Mensaje de uso**: constante `USAGE_DOCKER` con el ejemplo `docker compose run --rm gestor-facturas python -m agent.main /app/facturas/mi_factura.jpg`. Cuando la ruta resuelta es `None`, se imprime a stderr y `main` devuelve un código de uso dedicado.
4. **Código de salida de uso**: constante nueva `EXIT_USAGE = 64` fuera de `_EXIT_CODES`, para no colisionar con 1, 2 y 3 ya usados, y distinto de cero.
5. **Orden en `main`**: la resolución de la ruta ocurre antes de cargar política y levantar `McpToolbox`, para fallar rápido y sin iniciar servidores MCP cuando no hay ruta.

**File**: `Backend/docker-compose.yml` (opcional, solo documentación)

6. **Comentario del servicio**: aclarar que `docker compose up` pide la ruta por prompt (requiere `docker compose run` o `attach` para interactuar con el TTY). No se cambia ningún `command`, volumen ni variable.

## Testing Strategy

### Validation Approach

Primero se obtienen contraejemplos en el código sin corregir y luego se verifica el fix y la preservación. Las pruebas usan `pytest` y `hypothesis` (ya presentes en `Backend`), con `McpToolbox`/`run_cli` parcheados para no iniciar servidores MCP.

### Exploratory Bug Condition Checking

**Goal**: Mostrar el bug antes del fix y confirmar o refutar la causa raíz.

**Test Plan**: Llamar a `main(argv=[])` con stdin simulado (TTY y no TTY) y comprobar que no se produce `SystemExit` de argparse. Ejecutar sobre el código SIN corregir.

**Test Cases**:
1. **Sin argumentos, TTY**: `main(argv=[])` con stdin TTY simulado que entrega una ruta (falla en código original con `SystemExit(2)`).
2. **Sin argumentos, no TTY**: `main(argv=[])` con stdin no TTY (falla en código original con `SystemExit(2)` en lugar de uso y código distinto de cero).
3. **Ruta vacía en TTY**: el prompt recibe línea vacía (falla en código original por la misma causa).
4. **EOF en TTY**: el prompt recibe EOF (puede fallar en código original por la misma causa).

**Expected Counterexamples**:
- `SystemExit: 2` con `the following arguments are required: image_path` para `argv=[]`.
- Causa probable: posicional obligatorio, ausencia de fallback interactivo.

### Fix Checking

**Goal**: Verificar que para toda entrada con la condición del bug, el CLI corregido produce el comportamiento esperado.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := main_fixed(input)
  ASSERT expectedBehavior(result)
END FOR

FUNCTION expectedBehavior(result)
  RETURN (result.promptedForPath AND result.processedWith(enteredPath))
      OR (result.usageMessageShown AND result.exitCode != 0 AND NOT result.hasTraceback)
END FUNCTION
```

### Preservation Checking

**Goal**: Verificar que para toda entrada sin la condición del bug, el resultado es el mismo que el original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT main_original(input) = main_fixed(input)
END FOR
```

**Testing Approach**: Se recomienda property-based testing porque genera muchos casos de rutas y estados de TTY, detecta casos límite y da garantías fuertes de que lo no afectado no cambia.

**Test Plan**: Observar primero el comportamiento en el código sin corregir con `image_path` dado (pipeline parcheado que devuelve cada `status`), y escribir pruebas que lo capturen.

**Test Cases**:
1. **Ruta en argv**: `main(argv=[ruta])` pasa `ruta` a `run_cli` y devuelve el código de `_EXIT_CODES`, sin llamar al prompt, para cualquier TTY.
2. **Ruta por parámetro**: `main(image_path=ruta)` usa `ruta` sin leer stdin.
3. **Mapa de códigos**: cada `status` conserva su código de salida.
4. **Compose**: los servicios `finanzas-mcp`, `ocr-mcp`, `api-pruebas`, volúmenes y variables siguen igual (comprobación sobre el YAML).

### Unit Tests

- `_resolve_image_path` con ruta dada, TTY con entrada, TTY con vacío, TTY con EOF y no TTY.
- `main(argv=[])` no TTY: imprime el uso con `docker compose run`, devuelve `EXIT_USAGE` y no lanza excepción.
- `main(argv=[])` TTY con ruta: llama a `run_cli` con esa ruta recortada (`strip`).
- Rutas con espacios alrededor se recortan; rutas con espacios internos se conservan.

### Property-Based Tests

- Para cualquier ruta no vacía y cualquier estado de TTY, `main(argv=[ruta])` invoca el pipeline con exactamente `ruta` y nunca pregunta.
- Para cualquier cadena de solo espacios en TTY, `main` termina con `EXIT_USAGE` sin invocar el pipeline.
- Para cualquier ruta no vacía ingresada en el prompt TTY, el pipeline recibe la ruta recortada.

### Integration Tests

- Contenedor/proceso real con `docker compose run --rm -T gestor-facturas`: mensaje de uso y código distinto de cero sin traza.
- Flujo con TTY simulado (pty) y una imagen de `./facturas`: el prompt recibe la ruta y el pipeline completa el registro tras confirmación.
- `docker compose config`: los servicios con perfiles `mcp` y `api` mantienen sus comandos, volúmenes y variables.
