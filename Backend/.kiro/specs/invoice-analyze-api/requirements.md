# Requirements Document

## Introduction

Esta funcionalidad agrega al API de pruebas (`Backend/api_pruebas`) el endpoint `POST /facturas/analizar`. El endpoint recibe una imagen de factura por multipart, ejecuta el OCR existente, aplica las reglas de validación existentes (R1, R2, R3, R6; R4 deshabilitada) y devuelve en una sola respuesta los campos extraídos, los campos no identificados, el resultado de la validación y las advertencias. El endpoint no persiste ninguna transacción ni traza.

Además, se elimina el endpoint `POST /validar` (y su módulo `rutas/factura.py`), y se crea la carpeta `Backend/model` con un modelo `Transaction` cuyos campos coinciden con la tabla `transactions`.

Supuestos:
- El análisis reutiliza el extractor OCR y las funciones de validación ya existentes (`ServiciosNegocio`, `evaluar_factura`); no se introducen reglas nuevas.
- Los fallos del análisis (archivo inválido, OCR fallido, datos incompletos) se reportan dentro del cuerpo de la respuesta con código HTTP 200. Solo los errores de contrato de la solicitud (ver Requirement 5) se rechazan antes del análisis.
- La herramienta MCP `validar_factura` de `finanzas_mcp` no cambia.

## Glossary

- **API**: Aplicación FastAPI de `Backend/api_pruebas`.
- **Analizador**: Componente del API que atiende `POST /facturas/analizar`.
- **Servicio_OCR**: Extractor OCR existente (`ExtractorOcr`) que obtiene datos estructurados de una imagen.
- **Validador**: Función existente `evaluar_factura` que aplica las reglas R1, R2, R3 y R6.
- **Factura_Imagen**: Archivo con extensión permitida (`ALLOWED_EXTENSIONS`) y firma de contenido coincidente, con tamaño menor o igual a `max_upload_bytes`.
- **Campos_Factura**: Los campos analizables de una factura: `comercio`, `fecha`, `total`, `moneda`, `categoria`, `subtotal`, `iva`, `descripcion`.
- **Campos_Obligatorios**: Subconjunto de Campos_Factura exigido por R1: `comercio`, `fecha`, `total`, `moneda`, `categoria`.
- **Respuesta_Analisis**: Cuerpo JSON de la respuesta con las claves `campos`, `campos_no_identificados`, `validacion` y `advertencias`.
- **Modelo_Transaction**: Dataclass `Transaction` ubicada en `Backend/model`, alineada con la tabla `transactions`.
- **Tabla_Transactions**: Tabla `transactions` de la base SQLite con columnas `id`, `user_id`, `comercio`, `fecha`, `total`, `moneda`, `categoria`, `subtotal`, `iva`, `descripcion`, `created_at`.

## Requirements

### Requirement 1: Endpoint de análisis de factura

**User Story:** Como desarrollador del cliente, quiero enviar una imagen de factura y recibir los datos extraídos en una sola llamada, para revisar el resultado antes de registrar nada.

#### Acceptance Criteria

1. THE API SHALL exponer el endpoint `POST /facturas/analizar` que acepta una solicitud `multipart/form-data` con la parte de archivo `archivo`.
2. WHEN el Analizador recibe una Factura_Imagen, THE Analizador SHALL enviar la imagen al Servicio_OCR y mapear la salida a los Campos_Factura.
3. WHEN el Analizador completa el análisis de una Factura_Imagen, THE Analizador SHALL responder con código HTTP 200 y una Respuesta_Analisis.
4. THE API SHALL documentar `POST /facturas/analizar` en el esquema OpenAPI con el modelo de la Respuesta_Analisis.

### Requirement 2: Campos extraídos y no identificados

**User Story:** Como desarrollador del cliente, quiero distinguir los campos extraídos de los no identificados, para saber qué debe completar el usuario.

#### Acceptance Criteria

1. THE Respuesta_Analisis SHALL contener la clave `campos` con un objeto que incluye únicamente los Campos_Factura extraídos con valor no nulo.
2. THE Respuesta_Analisis SHALL contener la clave `campos_no_identificados` con la lista de nombres de los Campos_Factura que el Servicio_OCR no extrajo o devolvió vacíos.
3. THE Analizador SHALL colocar cada Campo_Factura en exactamente una de las dos claves, `campos` o `campos_no_identificados`.
4. WHEN el Servicio_OCR devuelve un valor de `categoria` ausente de la lista cerrada de categorías, THE Analizador SHALL colocar `categoria` en `campos_no_identificados`.

### Requirement 3: Resultado de validación

**User Story:** Como desarrollador del cliente, quiero recibir el resultado de las reglas de validación junto con el análisis, para saber si la factura sería aceptada.

#### Acceptance Criteria

1. THE Respuesta_Analisis SHALL contener la clave `validacion` con el indicador `valid` y la lista `reglas`, donde cada elemento incluye `regla`, `valid`, `code` y `message`.
2. WHEN el Analizador obtiene los Campos_Factura, THE Analizador SHALL invocar al Validador con los campos de `campos` y copiar su resultado en `validacion`.
3. WHEN `campos_no_identificados` contiene algún Campo_Obligatorio, THE Analizador SHALL devolver `validacion.valid` igual a `false` y la regla R1 con `valid` igual a `false`.
4. THE Analizador SHALL redactar los mensajes de `validacion` con la función `redactar` antes de incluirlos en la respuesta.

### Requirement 4: Advertencias y fallos de análisis

**User Story:** Como desarrollador del cliente, quiero recibir advertencias y errores de análisis dentro del cuerpo de la respuesta, para tratar todos los resultados con un solo flujo.

#### Acceptance Criteria

1. THE Respuesta_Analisis SHALL contener la clave `advertencias` con una lista de mensajes de texto, vacía cuando no existen advertencias.
2. WHEN la confianza global del Servicio_OCR es menor que el umbral de confianza configurado, THE Analizador SHALL agregar una advertencia de baja confianza a `advertencias`.
3. WHEN el Servicio_OCR señala contenido sospechoso en la imagen, THE Analizador SHALL agregar una advertencia de contenido sospechoso a `advertencias`.
4. IF el Servicio_OCR falla durante el análisis, THEN THE Analizador SHALL responder con código HTTP 200, `campos` vacío, todos los Campos_Factura en `campos_no_identificados` y un mensaje redactado del fallo en `advertencias`.
5. IF el archivo recibido tiene una extensión no permitida, una firma de contenido que no coincide con la extensión, o un tamaño mayor que `max_upload_bytes`, THEN THE Analizador SHALL responder con código HTTP 200, `campos` vacío, todos los Campos_Factura en `campos_no_identificados` y un mensaje redactado del motivo en `advertencias`.

### Requirement 5: Contrato de la solicitud

**User Story:** Como desarrollador del cliente, quiero un contrato de solicitud claro, para detectar errores de integración desde el primer intento.

#### Acceptance Criteria

1. IF la solicitud a `POST /facturas/analizar` no incluye la parte `archivo`, THEN THE API SHALL responder con el código HTTP 422 y el cuerpo de error estándar con código `VALIDATION_ERROR`.
2. WHEN el Analizador recibe una Factura_Imagen, THE Analizador SHALL procesar el contenido en memoria o en un archivo temporal y eliminar el archivo temporal antes de responder.

### Requirement 6: Análisis sin persistencia

**User Story:** Como responsable del sistema, quiero que el análisis no modifique datos, para usarlo como vista previa sin efectos secundarios.

#### Acceptance Criteria

1. WHEN el Analizador atiende una solicitud, THE Analizador SHALL completar el análisis sin insertar ni modificar filas en la Tabla_Transactions.
2. WHEN el Analizador atiende una solicitud, THE Analizador SHALL completar el análisis sin escribir archivos de traza ni de lote.
3. WHEN el Analizador atiende dos solicitudes consecutivas con la misma Factura_Imagen, THE Analizador SHALL dejar el conteo de filas de la Tabla_Transactions igual al conteo previo a la primera solicitud.

### Requirement 7: Eliminación de POST /validar

**User Story:** Como mantenedor, quiero eliminar `POST /validar`, para que el análisis de facturas tenga un único punto de entrada.

#### Acceptance Criteria

1. THE API SHALL dejar de registrar la ruta `POST /validar`.
2. WHEN un cliente envía una solicitud a `POST /validar`, THE API SHALL responder con el código HTTP 404 en el formato de error estándar.
3. THE API SHALL conservar el módulo de rutas de `POST /facturas/analizar` registrado en `app.py` en sustitución del módulo `rutas/factura.py` anterior.
4. THE API SHALL conservar sin cambios las rutas `/ocr`, `/transacciones`, `/pipeline`, `/batch` y `/trazas`.
5. WHEN se elimina `POST /validar`, THE API SHALL eliminar del código los esquemas y métodos que solo usaba esa ruta y que ninguna otra ruta referencia.

### Requirement 8: Modelo Transaction en Backend/model

**User Story:** Como desarrollador, quiero un modelo de datos en `Backend/model` que refleje la tabla `transactions`, para tipar las transacciones sin depender de `finanzas_mcp`.

#### Acceptance Criteria

1. THE Backend SHALL contener la carpeta `Backend/model` como paquete Python importable.
2. THE Modelo_Transaction SHALL definir los campos `id`, `user_id`, `comercio`, `fecha`, `total`, `moneda`, `categoria`, `subtotal`, `iva`, `descripcion` y `created_at`, con los mismos nombres que las columnas de la Tabla_Transactions.
3. THE Modelo_Transaction SHALL tipar `id` como entero opcional, `subtotal`, `iva`,  `descripcion` y `created_at` como opcionales, y `user_id`, `comercio`, `fecha`, `total`, `moneda`, `categoria` como obligatorios, de modo coherente con la nulabilidad de las columnas de la Tabla_Transactions.
4. WHEN el Modelo_Transaction se importa, THE Modelo_Transaction SHALL cargarse sin importar los paquetes `mcp` ni `finanzas_mcp`.
5. THE Modelo_Transaction SHALL permitir construir una instancia a partir de una fila de la Tabla_Transactions y convertirla a diccionario con las mismas claves que las columnas.
