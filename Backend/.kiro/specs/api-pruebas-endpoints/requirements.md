# Requirements Document

## Introduction

Esta funcionalidad agrega una API REST local (FastAPI sobre uvicorn) al proyecto gestor-facturas (carpeta `Backend/`) para facilitar las pruebas sin usar la CLI interactiva ni clientes MCP. La API expone endpoints para OCR, validación, listado de transacciones, ejecución no interactiva del pipeline completo, consulta de trazas y reinicio/siembra de la base de datos de pruebas. Genera documentación Swagger/OpenAPI automática.

La API es una capa delgada: reutiliza la lógica existente (`finanzas_mcp/business/*`, `finanzas_mcp/db/repository.py`, `ocr_mcp/ocr_client.py`, `ocr_mcp/server.py` y `agent/agent.py`) sin duplicarla ni debilitar las reglas R1-R11, el confinamiento de rutas, los tokens de confirmación, el aislamiento por usuario ni el tratamiento del contenido OCR como no confiable. La API utiliza la configuración existente del proyecto.

## Glossary

- **API_Pruebas**: Aplicación FastAPI local que expone los endpoints HTTP de prueba del gestor-facturas.
- **Usuario_Sesion**: Identificador de usuario de la configuración existente del proyecto; se usa como único `user_id` en todas las operaciones de la API_Pruebas.
- **Modo_Pruebas**: Estado de la API_Pruebas habilitado cuando la variable de entorno `API_TEST_MODE` vale `true`.
- **Servicio_OCR**: Lógica existente de `ocr_mcp` (`validar_ruta`, `OcrClient`, `wrap_untrusted`) que extrae datos de una imagen de factura.
- **Servicio_Validacion**: Funciones existentes de `finanzas_mcp/business/validacion.py` (reglas R1-R8).
- **Servicio_Transacciones**: Función existente `listar_transacciones` de `finanzas_mcp/business/transacciones.py`.
- **Repositorio**: Clase existente `TransactionRepository` de `finanzas_mcp/db/repository.py`.
- **Pipeline**: Clase existente `InvoicePipeline` de `agent/agent.py` que ejecuta los seis pasos del SKILL.
- **Politica**: Configuración cargada desde `politica.json` mediante `load_policy`.
- **Contenido_No_Confiable**: Texto devuelto por el Servicio_OCR, tratado siempre como datos y nunca como instrucciones (R10).
- **Traza**: Archivo JSON de ejecución del Pipeline escrito por `write_trace` en el directorio de trazas.
- **Respuestas_Provistas**: Lista ordenada de respuestas y tokens incluida en el request de ejecución del Pipeline, que sustituye la interacción del usuario.
- **Error_Estandar**: Cuerpo JSON de error de la API_Pruebas con los campos `code` y `message`.
- **Directorio_Imagenes**: Carpeta de facturas de la configuración existente del proyecto (`INVOICES_DIR`) dentro de la cual deben residir todas las imágenes procesadas.
- **Batch**: Ejecución del Pipeline en modo no interactivo sobre todas las imágenes permitidas de una subcarpeta del Directorio_Imagenes, identificada por un `batch_id` generado por el servidor.
- **Reporte_Batch**: Documento JSON (`summary.json`) con el resultado de un Batch: conteos por Clasificacion y el detalle de cada imagen.
- **Clasificacion**: Etiqueta asignada a cada imagen de un Batch: `ok`, `duplicada`, `no_valida`, `step_limit`, `token_limit`, `user_rejection` o `error`.

## Requirements

### Requirement 1: Ejecución de OCR

**User Story:** Como desarrollador, quiero ejecutar OCR sobre una imagen subida o ubicada en el directorio de facturas, para probar la extracción de forma aislada.

#### Acceptance Criteria

1. WHEN se recibe `POST /ocr` con una ruta de imagen, THE API_Pruebas SHALL validar la ruta con `validar_ruta` del Servicio_OCR antes de leer el archivo.
2. WHEN se recibe `POST /ocr` con un archivo subido, THE API_Pruebas SHALL guardar el archivo con un nombre generado por el servidor dentro del Directorio_Imagenes y procesarlo con el Servicio_OCR.
3. IF la ruta recibida resuelve fuera del Directorio_Imagenes, contiene traversal o tiene una extensión no permitida por el Servicio_OCR, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar.
4. IF el archivo subido supera 10 MB o no es una imagen con extensión permitida por el Servicio_OCR, THEN THE API_Pruebas SHALL responder con código 413 o 415 respectivamente y un Error_Estandar sin guardar el archivo.
5. WHEN el Servicio_OCR produce un resultado, THE API_Pruebas SHALL devolver el resultado envuelto con `wrap_untrusted` e `is_untrusted` igual a `true`.
6. IF el Servicio_OCR falla, THEN THE API_Pruebas SHALL responder con código 502 y un Error_Estandar que no contenga claves de API.
7. THE API_Pruebas SHALL ignorar cualquier instrucción contenida en el texto devuelto por el Servicio_OCR y tratarlo como Contenido_No_Confiable.

### Requirement 2: Validación de factura

**User Story:** Como desarrollador, quiero validar datos de una factura, para probar las reglas R1-R8 sin registrar nada.

#### Acceptance Criteria

1. WHEN se recibe `POST /validar` con datos de factura, THE API_Pruebas SHALL aplicar las validaciones del Servicio_Validacion y devolver el resultado de cada regla evaluada.
2. WHEN todas las reglas se cumplen, THE API_Pruebas SHALL responder con código 200 y `valid` igual a `true`.
3. IF alguna regla falla, THEN THE API_Pruebas SHALL responder con código 200, `valid` igual a `false` y el código y mensaje de cada regla incumplida.
4. IF el cuerpo del request no cumple el esquema (tipos o campos desconocidos), THEN THE API_Pruebas SHALL responder con código 422 y un Error_Estandar.
5. THE API_Pruebas SHALL delegar la evaluación de reglas al Servicio_Validacion sin reimplementar sus criterios.

### Requirement 3: Listado de transacciones

**User Story:** Como desarrollador, quiero listar transacciones con filtros, para verificar lo almacenado.

#### Acceptance Criteria

1. WHEN se recibe `GET /transacciones` con filtros permitidos, THE API_Pruebas SHALL invocar a `listar_transacciones` con esos filtros y el Usuario_Sesion.
2. WHEN se recibe `GET /transacciones` sin filtros, THE API_Pruebas SHALL devolver las transacciones del Usuario_Sesion con el límite por defecto del Servicio_Transacciones.
3. IF se recibe un filtro no permitido, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar derivado de `FilterError`.
4. IF el rango de fechas supera `max_rango_dias`, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar derivado de `DateRangeError`.
5. THE API_Pruebas SHALL devolver únicamente transacciones cuyo `user_id` coincida con el Usuario_Sesion.

### Requirement 4: Ejecución no interactiva del Pipeline

**User Story:** Como desarrollador, quiero ejecutar el pipeline completo con las respuestas incluidas en el request, para automatizar pruebas de extremo a extremo.

#### Acceptance Criteria

1. WHEN se recibe `POST /pipeline/run` con una imagen y Respuestas_Provistas, THE API_Pruebas SHALL ejecutar `InvoicePipeline.run` usando una implementación de `UserIO` que entrega las Respuestas_Provistas en orden.
2. WHEN el Pipeline termina, THE API_Pruebas SHALL responder con código 200, el `status`, el `termination_reason`, el identificador de la transacción si existe, el identificador de la Traza y los mensajes emitidos por `notify`.
3. IF el Pipeline solicita una respuesta y las Respuestas_Provistas se agotaron, THEN THE API_Pruebas SHALL entregar "sin respuesta" al Pipeline y reportar el resultado con el `status` que el Pipeline determine.
4. IF la ruta de la imagen resuelve fuera del Directorio_Imagenes, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar sin ejecutar el Pipeline.
5. THE API_Pruebas SHALL ejecutar el Pipeline con la Politica, los límites StepLimit y TokenLimit y el Usuario_Sesion de la configuración existente del proyecto.
6. THE API_Pruebas SHALL ejecutar las herramientas del Pipeline mediante las mismas funciones de negocio usadas por los endpoints de los requisitos 1 a 3, sin duplicar su lógica.
7. WHEN el Pipeline termina con `status` distinto de `success`, THE API_Pruebas SHALL responder con código 200 y reportar el `status` y el `termination_reason` del Pipeline.
8. WHEN dos ejecuciones del Pipeline se solicitan de forma concurrente, THE API_Pruebas SHALL mantener separadas las Respuestas_Provistas, los contadores de pasos y las Trazas de cada ejecución.

### Requirement 5: Pruebas en batch de imágenes

**User Story:** Como desarrollador, quiero procesar todas las imágenes de una subcarpeta con el pipeline y obtener un reporte clasificado, para evaluar lotes de facturas sin ejecutar cada imagen manualmente.

#### Acceptance Criteria

1. WHEN se recibe `POST /batch/run` con un nombre o ruta relativa de subcarpeta del Directorio_Imagenes (por ejemplo `test_batch_1`) y Respuestas_Provistas opcionales por imagen o por defecto, THE API_Pruebas SHALL generar un `batch_id` en el servidor, ejecutar el Pipeline en modo no interactivo sobre cada imagen de la subcarpeta y responder con código 200, el `batch_id` y el Reporte_Batch.
2. IF la subcarpeta recibida es absoluta, contiene traversal, o resuelve fuera del Directorio_Imagenes (incluso mediante enlaces simbólicos), THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar sin ejecutar el Pipeline.
3. IF la subcarpeta no existe o no es un directorio, THEN THE API_Pruebas SHALL responder con código 404 y un Error_Estandar sin crear directorio de salida.
4. IF la subcarpeta no contiene imágenes con extensión permitida por el Servicio_OCR, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar sin crear directorio de salida.
5. THE API_Pruebas SHALL seleccionar para el Batch únicamente los archivos de la subcarpeta cuya extensión esté permitida por el Servicio_OCR y procesarlos en orden alfabético ascendente por nombre de archivo.
6. IF la subcarpeta contiene más de 100 imágenes permitidas, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar sin ejecutar el Pipeline.
7. WHEN el Batch ejecuta el Pipeline sobre una imagen, THE API_Pruebas SHALL usar la implementación de `UserIO` del requisito 4 con las Respuestas_Provistas asignadas a esa imagen o, si no hay asignación, las Respuestas_Provistas por defecto.
8. WHILE Modo_Pruebas está habilitado, WHERE el request del Batch activa la auto-confirmación, THE API_Pruebas SHALL entregar al Pipeline los tokens de confirmación de prueba cada vez que el Pipeline solicite una confirmación que las Respuestas_Provistas no cubran.
9. IF el request del Batch activa la auto-confirmación mientras Modo_Pruebas está deshabilitado, THEN THE API_Pruebas SHALL responder con código 403 y un Error_Estandar sin ejecutar el Pipeline.
10. WHILE la auto-confirmación no está activa, WHEN el Pipeline solicita una confirmación no provista, THE API_Pruebas SHALL entregar "sin respuesta" al Pipeline, de modo que la imagen termine con `termination_reason` igual a `user_rejection` y sin registrar transacción.
11. WHEN el Pipeline termina para una imagen, THE API_Pruebas SHALL guardar la Traza de esa imagen en el directorio de salida `traces/batch/<batch_id>/`.
12. WHEN todas las imágenes han sido procesadas, THE API_Pruebas SHALL guardar el Reporte_Batch como `summary.json` en `traces/batch/<batch_id>/`.
13. WHEN el Pipeline termina para una imagen, THE API_Pruebas SHALL asignar a esa imagen exactamente una Clasificacion con su código y motivo, según los criterios 14 a 17.
14. WHEN el Pipeline termina con `status` igual a `success`, THE API_Pruebas SHALL asignar la Clasificacion `ok`.
15. WHEN el Pipeline detecta duplicados en el paso 4 de una imagen, o la imagen coincide en proveedor, fecha y monto con otra imagen anterior del mismo Batch, THE API_Pruebas SHALL asignar la Clasificacion `duplicada` e incluir el nombre de la imagen coincidente cuando exista.
16. WHEN el Pipeline termina con `termination_reason` igual a `validation_failure` por fallo de validación de campos, OCR, ruta o confianza, THE API_Pruebas SHALL asignar la Clasificacion `no_valida` e incluir los códigos de las reglas incumplidas.
17. WHEN el Pipeline termina con `termination_reason` igual a `step_limit`, `token_limit`, `user_rejection` o por una excepción, THE API_Pruebas SHALL asignar la Clasificacion `step_limit`, `token_limit`, `user_rejection` o `error` respectivamente, con el motivo correspondiente.
18. THE Reporte_Batch SHALL contener el `batch_id`, la subcarpeta, la fecha de ejecución, el total de imágenes, el conteo de imágenes por Clasificacion y, por cada imagen, el nombre de archivo, la Clasificacion, el motivo, el `status` y el identificador de su Traza.
19. IF el Pipeline falla o lanza una excepción para una imagen, THEN THE API_Pruebas SHALL clasificar esa imagen como `error` sin detalles de pila ni claves de API y continuar con la siguiente imagen del Batch.
20. WHEN se recibe `GET /batch`, THE API_Pruebas SHALL responder con la lista de Reportes_Batch del Usuario_Sesion con su `batch_id`, fecha, total de imágenes y conteos por Clasificacion.
21. WHEN se recibe `GET /batch/{batch_id}` con un identificador existente del Usuario_Sesion, THE API_Pruebas SHALL responder con código 200 y el Reporte_Batch completo.
22. IF el `batch_id` contiene caracteres distintos de letras, dígitos y guiones, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar sin acceder al sistema de archivos.
23. IF el `batch_id` no existe o pertenece a otro usuario, THEN THE API_Pruebas SHALL responder con código 404 y un Error_Estandar.
24. THE API_Pruebas SHALL devolver los Reportes_Batch y las Trazas del Batch sin valores de claves de API.
25. THE API_Pruebas SHALL ejecutar el Batch con el Usuario_Sesion como único `user_id` y devolver únicamente Reportes_Batch cuyo propietario coincida con el Usuario_Sesion.
26. WHEN dos Batches se solicitan de forma concurrente, incluso sobre la misma subcarpeta, THE API_Pruebas SHALL asignar un `batch_id` distinto a cada uno y mantener separados sus directorios de salida, Respuestas_Provistas, Trazas y Reportes_Batch.
27. WHERE el mecanismo de Trazas del requisito 6 pueda localizar archivos en `traces/batch/<batch_id>/`, THE API_Pruebas SHALL devolver las Trazas del Batch mediante `GET /trazas` y `GET /trazas/{trace_id}` con las mismas restricciones de usuario y de identificador.

### Requirement 6: Consulta de trazas

**User Story:** Como desarrollador, quiero consultar las trazas de ejecución, para depurar el comportamiento del Pipeline.

#### Acceptance Criteria

1. WHEN se recibe `GET /trazas`, THE API_Pruebas SHALL responder con la lista de Trazas del Usuario_Sesion con su identificador, fecha y `status`.
2. WHEN se recibe `GET /trazas/{trace_id}` con un identificador existente del Usuario_Sesion, THE API_Pruebas SHALL responder con código 200 y el contenido completo de la Traza.
3. IF el identificador no existe o pertenece a otro usuario, THEN THE API_Pruebas SHALL responder con código 404 y un Error_Estandar.
4. IF el identificador contiene caracteres distintos de letras, dígitos y guiones, THEN THE API_Pruebas SHALL responder con código 400 y un Error_Estandar sin acceder al sistema de archivos.
5. THE API_Pruebas SHALL devolver el contenido de las Trazas sin valores de claves de API.

### Requirement 7: Reset y seed de la base de datos de pruebas

**User Story:** Como desarrollador, quiero reiniciar y sembrar la base de datos de pruebas, para ejecutar pruebas repetibles.

#### Acceptance Criteria

1. WHILE Modo_Pruebas está deshabilitado, THE API_Pruebas SHALL responder con código 403 y un Error_Estandar a las solicitudes `POST /test/reset` y `POST /test/seed`.
2. WHILE Modo_Pruebas está habilitado, WHEN se recibe `POST /test/reset`, THE API_Pruebas SHALL eliminar únicamente las transacciones del Usuario_Sesion en la base de datos de `DB_PATH`.
3. WHILE Modo_Pruebas está habilitado, WHEN se recibe `POST /test/seed` con una lista de transacciones, THE API_Pruebas SHALL insertarlas mediante el Repositorio con el Usuario_Sesion como `user_id` y responder con la cantidad insertada.
4. WHILE Modo_Pruebas está habilitado, WHEN se recibe `POST /test/seed` sin cuerpo, THE API_Pruebas SHALL insertar un conjunto de transacciones de ejemplo predefinido.
5. IF `DB_PATH` apunta a un archivo que no está dentro de una ruta configurada como base de datos de pruebas, THEN THE API_Pruebas SHALL responder con código 403 a las solicitudes de reset y seed.
6. WHEN se ejecuta `POST /test/reset` seguido de `GET /transacciones`, THE API_Pruebas SHALL devolver una lista vacía para el Usuario_Sesion.

### Requirement 8: Documentación OpenAPI

**User Story:** Como desarrollador, quiero documentación Swagger automática, para explorar y probar los endpoints desde el navegador.

#### Acceptance Criteria

1. THE API_Pruebas SHALL servir la interfaz Swagger UI en `/docs` y el esquema OpenAPI en `/openapi.json`.
2. THE API_Pruebas SHALL describir en el esquema OpenAPI cada endpoint con su resumen, modelo de request, modelos de respuesta y códigos de error.
3. THE API_Pruebas SHALL usar modelos de datos tipados para todos los cuerpos de request y respuesta.

### Requirement 9: Arranque local y alcance de red

**User Story:** Como desarrollador, quiero iniciar la API con un comando simple y restringida a mi equipo, para evitar exponer funciones de prueba.

#### Acceptance Criteria

1. THE API_Pruebas SHALL iniciarse con uvicorn mediante un módulo de aplicación documentado en el `README.md`.
2. THE API_Pruebas SHALL enlazarse por defecto a `127.0.0.1`.
3. WHEN el host configurado es distinto de `127.0.0.1` y de `localhost`, THE API_Pruebas SHALL registrar una advertencia de exposición en red al iniciar.
4. THE `requirements.txt` SHALL listar `fastapi`, `uvicorn` y `python-multipart` con versiones fijas.
5. THE API_Pruebas SHALL importar la lógica de negocio desde los módulos existentes sin modificar sus reglas ni su comportamiento.

### Requirement 10: Manejo uniforme de errores

**User Story:** Como desarrollador, quiero respuestas de error consistentes, para interpretar fallos fácilmente.

#### Acceptance Criteria

1. WHEN ocurre un error controlado, THE API_Pruebas SHALL responder con un Error_Estandar y el código HTTP correspondiente.
2. IF ocurre una excepción no controlada, THEN THE API_Pruebas SHALL responder con código 500 y un Error_Estandar sin rastros de pila ni valores de claves de API.
3. WHEN una herramienta existente devuelve `isError`, THE API_Pruebas SHALL convertir el código y mensaje de la herramienta en un Error_Estandar sin alterar el código de la regla.
