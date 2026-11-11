# Documento de Diseño: docker-env-file

## Overview

El stack Docker de `Backend` (servicios `gestor-facturas`, `finanzas-mcp`, `ocr-mcp` y `api-pruebas`) debe obtener sus variables de entorno desde el archivo `Backend/.env`. Hoy `docker-compose.yml` ya declara `env_file: .env` (con `required: false`) y usa `${MCP_USER_ID:-default_user}` y `${API_TEST_MODE:-false}`, pero en la práctica las variables no llegan al contenedor.

La investigación encontró la causa raíz: el `.env` actual está escrito con sintaxis de PowerShell (copiado del bloque del README), por ejemplo `$env:ANTHROPIC_API_KEY ="..."   # comentario`. Esa sintaxis no es un formato dotenv válido. Se verificó con Docker Compose v2.32.4 en un directorio temporal: `docker compose config` falla con `unexpected character "$" in variable name "$env:FOO ..."`. Por lo tanto, el compose no puede leer ni el `env_file` ni la interpolación `${...}`, y el usuario no logra que `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `OCR_MODEL`, `MCP_USER_ID` lleguen a los contenedores.

La estrategia es mínima y declarativa, sin tocar código Python de negocio:
- Definir un contrato de `.env` en formato dotenv (`CLAVE=valor`) y publicarlo como `Backend/.env.example` (versionado, sin secretos).
- Convertir el `.env` local al formato dotenv conservando sus valores.
- Mantener en `docker-compose.yml` el `env_file` como única fuente de las variables configurables y conservar como valores fijos solo las rutas internas del contenedor.
- Documentar en el README la diferencia entre el `.env` (Docker) y el bloque `$env:` de PowerShell (ejecución local).

## Hallazgos de la investigación

| Elemento | Estado actual | Implicación |
|---|---|---|
| `Backend/.env` | Líneas `$env:NOMBRE ="valor"   # comentario` | Inválido para Docker Compose; es la causa raíz. También está ignorado por git (`.gitignore`) y por Docker (`.dockerignore`). |
| `Backend/.env.example` | No existe | No hay contrato versionado del formato ni de las variables soportadas. |
| `docker-compose.yml` | `env_file` con `required: false`; `environment` fija `DB_PATH`, `INVOICES_DIR`, `TRACES_DIR`; `MCP_USER_ID` y `API_TEST_MODE` por interpolación | La estructura es correcta; falla solo por el contenido del `.env`. |
| `Dockerfile` | `ENV DB_PATH=/app/data/facturas.db`, `ENV INVOICES_DIR=/app/facturas`; `.env` excluido por `.dockerignore` | Correcto: los secretos no se hornean en la imagen. Se conserva. |
| Código Python | Lee `os.environ` (`agent/main.py`, `ocr_mcp/*`, `finanzas_mcp/server.py`). Solo `api_pruebas/config.py` usa `python-dotenv` | Dentro del contenedor el código depende de que Compose inyecte las variables. |
| `README.md` | Sección 6 dice "Las claves se leen de un archivo `.env`" pero no explica el formato | Induce a copiar el bloque `$env:` de PowerShell al `.env`. |

Variables que el código lee del entorno:

| Variable | Lectura | Valor en contenedor |
|---|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | `ocr_mcp/ocr_client.py` | Desde `.env` |
| `LLM_PROVIDER` | `ocr_mcp/ocr_client.py` | Desde `.env` |
| `OCR_MODEL` | `ocr_mcp/server.py`, `api_pruebas/config.py` | Desde `.env` |
| `MCP_USER_ID` | `agent/main.py`, `finanzas_mcp/server.py`, `api_pruebas/config.py` | Desde `.env`; por defecto `default_user` |
| `API_TEST_MODE` | `api_pruebas/config.py` | Desde `.env`; por defecto `false` (solo `api-pruebas`) |
| `MAX_IMAGE_BYTES`, `BATCH_MAX_IMAGES`, `API_TEST_DB_ALLOWLIST`, `BATCH_TRACES_DIR`, `POLICY_PATH` | Varios | Opcionales, desde `.env` |
| `DB_PATH`, `INVOICES_DIR`, `TRACES_DIR` | Varios | Fijas en `docker-compose.yml` (rutas del contenedor, ligadas a los volúmenes) |

## Architecture

```mermaid
graph TD
    ENV[Backend/.env<br/>formato dotenv CLAVE=valor] -->|interpolación ${VAR:-default}| COMPOSE[docker-compose.yml]
    ENV -->|env_file| SVC
    EX[Backend/.env.example<br/>contrato versionado] -.copiar y completar.-> ENV
    COMPOSE -->|environment: rutas fijas del contenedor| SVC[Servicios: gestor-facturas,<br/>finanzas-mcp, ocr-mcp, api-pruebas]
    DI[.dockerignore excluye .env] -.no se hornea en la imagen.-> IMG[Imagen gestor-facturas:latest]
    IMG --> SVC
    SVC -->|os.environ| APP[agent / ocr_mcp / finanzas_mcp / api_pruebas]
```

### Precedencia de valores

Docker Compose resuelve cada variable del contenedor en este orden (de mayor a menor):

1. `environment:` del servicio en `docker-compose.yml`.
2. `env_file:` (`Backend/.env`).
3. `ENV` del `Dockerfile`.

Consecuencias de diseño:
- `DB_PATH`, `INVOICES_DIR` y `TRACES_DIR` permanecen en `environment:` para que un `.env` pensado para ejecución local (`./data/facturas.db`) no rompa las rutas montadas como volúmenes en `/app/...`.
- Las demás variables (claves, `LLM_PROVIDER`, `OCR_MODEL`, `MCP_USER_ID`, etc.) llegan por `env_file` y no se duplican en `environment:`.
- `MCP_USER_ID` y `API_TEST_MODE` conservan su interpolación con valor por defecto, que Compose lee del mismo `Backend/.env` (archivo de proyecto por defecto).

## Components and Interfaces

### Componente 1: `Backend/.env.example` (nuevo)

**Propósito**: Contrato versionado y sin secretos del archivo `.env` en formato dotenv.

**Interfaz (formato)**:
```dotenv
# Proveedor de LLM: openai | anthropic (opcional; se detecta por la clave)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
# Opcional; por defecto gpt-4o / claude-3-5-sonnet-latest
OCR_MODEL=
# Usuario de la sesión
MCP_USER_ID=usuario_prueba
# Solo api-pruebas
API_TEST_MODE=false
```

**Responsabilidades**:
- Listar las variables configurables con comentarios en líneas propias (nunca al final de un valor).
- No contener claves reales.
- Indicar que `DB_PATH`, `INVOICES_DIR` y `TRACES_DIR` los fija el compose dentro del contenedor.

### Componente 2: `Backend/.env` (local, ignorado por git)

**Propósito**: Valores reales del usuario, en formato dotenv.

**Reglas de formato**:
- Una variable por línea: `NOMBRE=valor` o `NOMBRE="valor"`, sin prefijo `$env:`, sin espacios alrededor de `=`.
- Los comentarios van en líneas propias que empiezan con `#`.
- Los valores existentes (clave, proveedor, modelo, usuario) se conservan; solo cambia la sintaxis.
- Si `DB_PATH` / `INVOICES_DIR` se mantienen para uso local, el compose los sobrescribe dentro del contenedor.

### Componente 3: `Backend/docker-compose.yml` (ajuste mínimo)

**Propósito**: Seguir inyectando el `.env` a los cuatro servicios mediante el ancla `x-comun`.

**Cambios**:
- Se conserva `env_file` con `path: .env` y `required: false` (los servicios arrancan con los valores por defecto si no hay `.env`).
- Se añaden comentarios que documentan la precedencia y que las variables configurables se definen en `.env`.
- No cambian `build`, `image`, `volumes`, `command`, `profiles`, `ports`, `stdin_open`, `tty` ni `environment`.

```yaml
x-comun: &comun
  env_file:
    - path: .env
      required: false
  environment: &comun-env
    DB_PATH: /app/data/facturas.db
    INVOICES_DIR: /app/facturas
    TRACES_DIR: /app/traces
    MCP_USER_ID: ${MCP_USER_ID:-default_user}
```

### Componente 4: `Backend/Dockerfile` y `.dockerignore` (sin cambios)

Se conservan `ENV DB_PATH`, `ENV INVOICES_DIR` y la exclusión de `.env` en `.dockerignore`, de modo que ningún secreto queda en las capas de la imagen.

### Componente 5: `Backend/README.md` (sección 6 "Docker")

**Cambios**:
- Explicar que el `.env` usa formato dotenv (`CLAVE=valor`) y que se crea con `Copy-Item .env.example .env`.
- Aclarar que el bloque `$env:...` de la sección de ejecución local es solo para la sesión de PowerShell y no debe pegarse en `.env`.
- Indicar qué variables toma el contenedor del `.env` y cuáles fija el compose.

## Data Models

### Modelo: línea válida de `.env`

```text
Linea     := Comentario | Vacia | Asignacion
Comentario:= '#' texto
Vacia     := ''
Asignacion:= NOMBRE '=' Valor
NOMBRE    := [A-Za-z_][A-Za-z0-9_]*
Valor     := sin_comillas | '"' texto '"' | "'" texto "'"
```

**Reglas de validación**:
- `NOMBRE` no puede contener `$` ni `:` (descarta `$env:NOMBRE`).
- Los comentarios al final de línea no forman parte del contrato; se usan líneas `#` independientes.
- `.env.example` no puede contener valores que parezcan claves reales (`ANTHROPIC_API_KEY` y `OPENAI_API_KEY` vacías).

## Error Handling

### Escenario 1: `.env` con sintaxis PowerShell

**Condición**: El `.env` contiene líneas `$env:NOMBRE ="valor"`.
**Respuesta**: Docker Compose aborta con `unexpected character "$" in variable name`.
**Recuperación**: Convertir a `NOMBRE=valor` siguiendo `.env.example`. El README documenta el formato.

### Escenario 2: `.env` ausente

**Condición**: No existe `Backend/.env`.
**Respuesta**: Gracias a `required: false`, Compose arranca con los valores por defecto (`default_user`, `API_TEST_MODE=false`). La clave del LLM no estará presente y `ocr_mcp` ya informa su ausencia.
**Recuperación**: Crear `.env` desde `.env.example`.

### Escenario 3: `.env` con rutas locales

**Condición**: El `.env` define `DB_PATH=./data/facturas.db`.
**Respuesta**: `environment:` del compose prevalece y el contenedor usa `/app/data/facturas.db`.
**Recuperación**: No requiere acción; es el comportamiento preservado.

## Testing Strategy

### Pruebas unitarias (pytest, sin Docker en ejecución)

- `.env.example` existe y se parsea con `dotenv_values` sin errores.
- Cada línea no vacía y no comentada de `.env.example` cumple el modelo `NOMBRE=valor` (sin `$`, sin `:` en el nombre).
- `.env.example` incluye al menos `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OCR_MODEL`, `MCP_USER_ID` y `API_TEST_MODE`, y no contiene valores de clave no vacíos.
- Con PyYAML, `docker-compose.yml` conserva `env_file` con `.env` en el ancla común y los cuatro servicios heredan de ella.
- `environment` conserva `DB_PATH=/app/data/facturas.db`, `INVOICES_DIR=/app/facturas`, `TRACES_DIR=/app/traces`; los volúmenes, comandos, perfiles y puertos permanecen sin cambios.
- `.dockerignore` sigue excluyendo `.env`.

### Pruebas basadas en propiedades

Las propiedades de corrección se definirán después de aprobar los requisitos. Esta funcionalidad es sobre todo configuración declarativa, por lo que el peso recae en pruebas de ejemplo; solo el validador de formato dotenv es una función pura apta para propiedades (Hypothesis ya está en `requirements.txt`).

### Prueba de integración (opcional)

Si `docker` está disponible, `docker compose config` con un `.env` copiado de `.env.example` debe terminar con código 0 y mostrar `MCP_USER_ID` y las rutas fijas para los cuatro servicios. Se omite con `pytest.skip` si `docker` no está instalado. La salida no debe imprimirse en los logs de la prueba, porque `config` expande los valores de las claves.

## Security Considerations

- `.env` sigue ignorado por git y por `.dockerignore`; `.env.example` no lleva secretos.
- El fix no imprime ni copia el valor de `ANTHROPIC_API_KEY`; la conversión del `.env` local conserva el valor sin mostrarlo.
- Las pruebas no deben volcar la salida de `docker compose config`.

## Dependencies

- Docker Compose v2 (soporte de `env_file` con `path` y `required`; verificado con v2.32.4).
- `python-dotenv==1.1.0` (ya en `requirements.txt`) para validar el formato en pruebas.
- PyYAML (disponible en el entorno virtual como dependencia transitiva) para leer el compose en pruebas; las pruebas usan `pytest.importorskip("yaml")`.

## Fuera de alcance

- Cambiar el código Python de negocio (`agent`, `ocr_mcp`, `finanzas_mcp`, `api_pruebas`).
- Cargar `.env` automáticamente en ejecución local fuera de Docker (solo `api_pruebas` lo hace hoy).
- Modificar volúmenes, comandos, perfiles o puertos del compose.
