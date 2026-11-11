# Bugfix Requirements Document

## Introduction

Al ejecutar `docker compose up --build` en `Backend/`, el servicio `gestor-facturas` arranca el contenedor con el `CMD ["python", "-m", "agent.main"]` del Dockerfile, sin comando ni argumentos adicionales en `docker-compose.yml`. El CLI exige el argumento posicional `image_path`, por lo que termina de inmediato con el error `python -m agent.main: error: the following arguments are required: image_path`. El contenedor queda inutilizable con el flujo por defecto de Compose, aunque tiene `stdin_open` y `tty` habilitados para uso interactivo.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN el servicio `gestor-facturas` se inicia con `docker compose up --build` sin argumentos adicionales THEN the system ejecuta `python -m agent.main` sin `image_path` y termina con el error de argparse "the following arguments are required: image_path"

1.2 WHEN el contenedor arranca sin `image_path` y con `stdin_open`/`tty` habilitados THEN the system no solicita la ruta de la imagen de forma interactiva y finaliza con código de salida distinto de cero

1.3 WHEN el contenedor arranca sin `image_path` THEN the system no indica cómo invocar correctamente el CLI dentro de Docker (por ejemplo, con `docker compose run --rm gestor-facturas python -m agent.main /app/facturas/mi_factura.jpg`)

### Expected Behavior (Correct)

2.1 WHEN el servicio `gestor-facturas` se inicia con `docker compose up --build` sin argumentos adicionales THEN the system SHALL arrancar sin el error de argparse por `image_path` faltante

2.2 WHEN el CLI se inicia sin `image_path` y stdin es interactivo (TTY) THEN the system SHALL solicitar la ruta de la imagen mediante un prompt y continuar el procesamiento con la ruta ingresada

2.3 WHEN el CLI se inicia sin `image_path` y stdin no es interactivo, o el usuario no ingresa una ruta THEN the system SHALL mostrar un mensaje de uso claro con un ejemplo de invocación en Docker y terminar con un código de salida distinto de cero sin traza de error

### Unchanged Behavior (Regression Prevention)

3.1 WHEN el CLI se invoca con `image_path` (por ejemplo, `docker compose run --rm gestor-facturas python -m agent.main /app/facturas/mi_factura.jpg`) THEN the system SHALL CONTINUE TO procesar la imagen y registrar la transacción tras confirmación, con los mismos códigos de salida (`success`=0, `validation_error`=1, `user_abort`=2, `step_limit`/`token_limit`=3)

3.2 WHEN se invoca `main(image_path=...)` programáticamente o con `argv` que incluye `image_path` THEN the system SHALL CONTINUE TO usar esa ruta sin pedirla de nuevo

3.3 WHEN se inician los servicios `finanzas-mcp`, `ocr-mcp` o `api-pruebas` con sus perfiles (`mcp`, `api`) THEN the system SHALL CONTINUE TO ejecutar sus comandos propios sin cambios

3.4 WHEN se montan los volúmenes `./data`, `./facturas` y `./traces` y se definen las variables `DB_PATH`, `INVOICES_DIR`, `TRACES_DIR` y `MCP_USER_ID` THEN the system SHALL CONTINUE TO persistir datos y trazas en el host con la misma configuración
