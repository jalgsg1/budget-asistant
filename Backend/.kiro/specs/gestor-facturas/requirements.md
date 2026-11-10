# Requirements Document

## Introduction

El sistema `gestor-facturas` es un asistente personal de finanzas basado en agente que permite al usuario fotografiar facturas físicas o digitales y registrarlas automáticamente en una base de datos SQLite local. El agente orquesta un pipeline de seis pasos: extracción de texto mediante OCR basado en LLM con visión, validación de campos y coherencia aritmética, detección de duplicados y confirmación del usuario antes de persistir la transacción. El servidor MCP `finanzas-mcp` actúa como guardián de escritura independiente que revalida todos los datos sin confiar en el agente. El sistema opera exclusivamente desde la interfaz de línea de comandos (CLI) e implementa defensa en profundidad contra inyecciones indirectas en el contenido de imágenes.

Quedan fuera del alcance: ingresos, gastos fijos, aplicación móvil y cualquier interfaz gráfica (React Native). El sistema procesa exactamente una imagen por factura; facturas que requieran más de una fotografía para capturar todos sus campos quedan fuera del alcance. Las facturas del conjunto de evaluación deben fotografiarse de forma que todos los campos relevantes (comercio, fecha, total, moneda) sean visibles en una sola imagen.

> **Nota — Evolución prevista hacia backend REST**
> Esta spec cubre el motor de ingesta y conciliación (OCR → validación → agente → SQLite) que es el objeto de estudio del experimento. En una fase posterior, el mismo motor deberá exponerse como un backend HTTP con endpoints consultables desde un front-end o desde herramientas como Postman. El diseño del motor (servidores MCP, capa SQLite, modelos de datos) debe mantenerse desacoplado de la interfaz de entrada para facilitar esa transición: la lógica de negocio de inanzas-mcp no debe depender de stdin/stdout, de modo que pueda ser invocada tanto desde el agente CLI como desde un handler HTTP en el futuro.

---

## Glossary

- **Agent**: Componente de orquestación que ejecuta el pipeline de seis pasos sobre cada factura y decide el flujo de control según los resultados de cada herramienta.
- **finanzas-mcp**: Servidor MCP propio que expone las herramientas `validar_factura`, `buscar_duplicados`, `listar_transacciones` y `registrar_transaccion`; no confía en el agente y revalida todo dato recibido.
- **ocr-mcp**: Servidor MCP que expone `ocr_imagen`; extrae texto de imágenes usando un LLM con visión (p. ej. GPT-4o o Gemini) y devuelve el resultado como contenido no confiable.
- **OCR_Result**: Texto extraído de una imagen de factura, tratado como dato no confiable en todo momento.
- **Transaction**: Registro de un gasto con los campos comercio, fecha, total, moneda, categoría y, opcionalmente, subtotal e IVA.
- **ConfirmationToken**: Señal explícita proporcionada por el usuario a través de la CLI antes de que el agente ejecute `registrar_transaccion`.
- **Skill**: Procedimiento formal documentado en `SKILL.md` que describe los pasos del agente, las reglas de negocio y el criterio de parada.
- **Policy**: Archivo `politica.json` que declara las herramientas permitidas, las que requieren confirmación, las denegadas y las ocultas, junto con los límites de pasos y tokens.
- **Trace**: Registro por ejecución que incluye cada llamada a herramienta, decisión del agente, tokens consumidos y duración.
- **EvaluationSet**: Conjunto de ≥ 45 facturas etiquetadas manualmente utilizado para medir exactitud y reproducibilidad.
- **HighAmountThreshold**: Valor monetario configurable por encima del cual se exige un ConfirmationToken adicional antes de persistir la transacción.
- **ClosedCategoryList**: Catálogo predefinido de categorías de gasto; solo valores de esta lista son aceptados por el servidor.
- **SQLite_DB**: Base de datos SQLite local donde se persisten las transacciones validadas.
- **StepLimit**: Máximo de 8 pasos de agente permitidos por ejecución de factura.
- **TokenLimit**: Tope de tokens de LLM permitidos por ejecución de factura, definido en `politica.json`.

---

## Requirements

### Requirement 1: Extracción de texto mediante OCR

**User Story:** As a usuario, I want the system to extract text from an invoice image using a vision-capable LLM, so that I can process physical or digital receipts without manual transcription.

#### Acceptance Criteria

1. WHEN the Agent receives a valid image file path, THE ocr-mcp SHALL invoke `ocr_imagen(ruta)` and return the extracted OCR_Result wrapped as untrusted content.
2. WHEN `ocr_imagen` is called, THE ocr-mcp SHALL validate that the file path is located within the designated invoices folder before processing.
3. WHEN `ocr_imagen` is called, THE ocr-mcp SHALL validate that the image type and file size are within the accepted limits before invoking the vision LLM.
4. IF the image file path is outside the designated invoices folder, THEN THE ocr-mcp SHALL reject the request and return an error describing the path violation.
5. WHEN an OCR_Result is returned, THE Agent SHALL treat all extracted text as untrusted data and SHALL NOT execute any instructions found within that text. (R10)
6. IF the OCR_Result contains text that appears to be a command or instruction, THEN THE Agent SHALL process that text solely as invoice field data and ignore its directive content. (R10)
7. WHEN OCR confidence for a field is below the accepted threshold, THE Agent SHALL retry `ocr_imagen`; IF confidence remains low after retry, THEN THE Agent SHALL request clarification from the user via the CLI.

---

### Requirement 2: Validación de campos obligatorios

**User Story:** As a usuario, I want the server to reject any invoice that is missing required fields, so that incomplete data is never persisted in the database.

#### Acceptance Criteria

1. WHEN `validar_factura(datos)` is called, THE finanzas-mcp SHALL verify the presence of all five required fields: comercio, fecha, total, moneda, and categoría. (R1)
2. IF any of the required fields (comercio, fecha, total, moneda, categoría) is absent or empty, THEN THE finanzas-mcp SHALL reject the validation and return an error message identifying each missing field. (R1)
3. WHEN `registrar_transaccion` is called, THE finanzas-mcp SHALL revalidate the presence of all five required fields independently of any prior validation performed by the Agent. (R1)

---

### Requirement 3: Validación de fecha

**User Story:** As a usuario, I want the server to reject dates that are invalid or in the future, so that no transaction is recorded with an erroneous date.

#### Acceptance Criteria

1. WHEN `validar_factura(datos)` is called, THE finanzas-mcp SHALL verify that the `fecha` field conforms to a recognized date format. (R2)
2. IF the `fecha` field does not conform to a recognized date format, THEN THE finanzas-mcp SHALL reject the validation and return a date-format error message. (R2)
3. IF the `fecha` field represents a date later than the current system date, THEN THE finanzas-mcp SHALL reject the validation and return a future-date error message. (R2)
4. WHEN `registrar_transaccion` is called, THE finanzas-mcp SHALL revalidate the date independently of the Agent's prior validation. (R2)

---

### Requirement 4: Validación de moneda

**User Story:** As a usuario, I want the server to accept only CRC and USD as valid currencies, so that transactions with unsupported currencies are never stored.

#### Acceptance Criteria

1. WHEN `validar_factura(datos)` is called, THE finanzas-mcp SHALL verify that the `moneda` field contains an ISO 4217 code that is either CRC or USD. (R3)
2. IF the `moneda` field contains a value other than CRC or USD, THEN THE finanzas-mcp SHALL reject the validation and return a currency error message. (R3)
3. WHEN `registrar_transaccion` is called, THE finanzas-mcp SHALL revalidate the currency independently of the Agent's prior validation. (R3)

---

### Requirement 5: Coherencia aritmética

**User Story:** As a usuario, I want the server to verify that subtotal plus IVA equals the total within a tolerance of ±0.01, so that arithmetic errors in invoices are caught before registration.

#### Acceptance Criteria

1. WHEN `validar_factura(datos)` is called and the fields `subtotal` and `IVA` are both present, THE finanzas-mcp SHALL verify that `subtotal + IVA` equals `total` within a tolerance of ±0.01. (R4)
2. IF `subtotal + IVA` differs from `total` by more than 0.01, THEN THE finanzas-mcp SHALL reject the validation and return an arithmetic-inconsistency error message. (R4)
3. WHEN the Agent receives an arithmetic-inconsistency error, THE Agent SHALL request confirmation from the user specifying which value (subtotal, IVA, or total) is correct before retrying `validar_factura`. (R4)
4. WHEN `registrar_transaccion` is called with subtotal and IVA present, THE finanzas-mcp SHALL revalidate arithmetic coherence independently of the Agent's prior validation. (R4)

---

### Requirement 6: Detección de duplicados

**User Story:** As a usuario, I want the system to detect potential duplicate invoices before saving, so that the same expense is not recorded twice.

#### Acceptance Criteria

1. WHEN the Agent prepares to call `registrar_transaccion`, THE Agent SHALL first call `buscar_duplicados(comercio, fecha, total)` for the active user's account. (R5)
2. WHEN `buscar_duplicados` is called, THE finanzas-mcp SHALL return at most 10 results matching the combination of comercio, fecha, and total for the active user's account. (R5, R9)
3. IF `buscar_duplicados` returns one or more matching results, THEN THE Agent SHALL present the matches to the user via the CLI and SHALL NOT call `registrar_transaccion` until the user provides explicit confirmation to proceed. (R5)
4. WHEN `registrar_transaccion` is called, THE finanzas-mcp SHALL independently verify the absence of a duplicate transaction before persisting the record. (R5)
5. IF a duplicate is detected by `registrar_transaccion`, THEN THE finanzas-mcp SHALL reject the write and return a duplicate-detected error message. (R5)

---

### Requirement 7: Validación de categoría

**User Story:** As a usuario, I want the server to reject any category not in the predefined catalog, so that expenses are always classified consistently.

#### Acceptance Criteria

1. WHEN `validar_factura(datos)` is called, THE finanzas-mcp SHALL verify that the `categoría` field contains a value from the ClosedCategoryList. (R6)
2. IF the `categoría` field contains a value not present in the ClosedCategoryList, THEN THE finanzas-mcp SHALL reject the validation and return a category-not-found error message listing the accepted categories. (R6)
3. WHEN the Agent encounters an ambiguous category from the OCR_Result, THE Agent SHALL present the ClosedCategoryList options to the user via the CLI and request a selection before calling `validar_factura`. (R6)
4. WHEN `registrar_transaccion` is called, THE finanzas-mcp SHALL revalidate the category against the ClosedCategoryList independently of the Agent's prior validation. (R6)

---

### Requirement 8: Confirmación del usuario antes de escribir

**User Story:** As a usuario, I want the system to require my explicit confirmation before registering any transaction, so that no expense is saved without my approval.

#### Acceptance Criteria

1. WHEN the Agent has completed all validation and duplicate-check steps successfully, THE Agent SHALL request a ConfirmationToken from the user via the CLI before calling `registrar_transaccion`. (R8)
2. IF the user does not provide a ConfirmationToken, THEN THE Agent SHALL NOT call `registrar_transaccion` and SHALL inform the user that the transaction was not saved. (R8)
3. WHEN `registrar_transaccion` is called, THE finanzas-mcp SHALL verify that a valid ConfirmationToken is present in the request before persisting the transaction. (R8)
4. IF `registrar_transaccion` is called without a valid ConfirmationToken, THEN THE finanzas-mcp SHALL reject the write and return an authorization error message. (R8)

---

### Requirement 9: Confirmación adicional para montos altos

**User Story:** As a usuario, I want the system to require additional confirmation for high-value transactions, so that large expenses are never recorded by mistake.

#### Acceptance Criteria

1. WHEN the Agent prepares a transaction whose `total` exceeds the HighAmountThreshold, THE Agent SHALL present the amount to the user and request explicit confirmation before proceeding. (R7)
2. WHERE the HighAmountThreshold is configured in `politica.json`, THE finanzas-mcp SHALL apply the same threshold value when processing `registrar_transaccion`. (R7)
3. IF the `total` of a transaction exceeds the HighAmountThreshold and no high-amount ConfirmationToken is present in the request, THEN THE finanzas-mcp SHALL reject the write and return a high-amount confirmation error message. (R7)

---

### Requirement 10: Consulta de transacciones

**User Story:** As a usuario, I want to list my recorded transactions with controlled filters, so that I can review my expenses without exposing other users' data.

#### Acceptance Criteria

1. WHEN `listar_transacciones(filtros)` is called, THE finanzas-mcp SHALL apply a filter whitelist and reject any filter key not in the approved list. (R9)
2. WHEN `listar_transacciones(filtros)` is called with a date range, THE finanzas-mcp SHALL enforce a maximum date-range window and reject requests that exceed it. (R9)
3. THE finanzas-mcp SHALL restrict all query results of `listar_transacciones` and `buscar_duplicados` to transactions belonging exclusively to the active user's account. (R9)
4. IF a filter key outside the whitelist is supplied to `listar_transacciones`, THEN THE finanzas-mcp SHALL reject the request and return an invalid-filter error message. (R9)

---

### Requirement 11: Límite de pasos y tokens del agente

**User Story:** As a usuario, I want each invoice processing run to be bounded in steps and token usage, so that runaway executions are automatically stopped.

#### Acceptance Criteria

1. WHILE processing a single invoice, THE Agent SHALL count each tool call and decision step; WHEN the StepLimit of 8 is reached, THE Agent SHALL stop processing and notify the user via the CLI. (R11)
2. WHILE processing a single invoice, THE Agent SHALL track cumulative token usage; WHEN the TokenLimit defined in `politica.json` is reached, THE Agent SHALL stop processing and notify the user via the CLI. (R11)
3. IF the Agent stops due to StepLimit or TokenLimit, THEN THE Agent SHALL NOT call `registrar_transaccion` and SHALL log the reason for the stop in the Trace. (R11)

---

### Requirement 12: Archivo de políticas (`politica.json`)

**User Story:** As a developer, I want a machine-readable policy file that declares the permission level of each tool and the operational limits, so that autonomy is explicitly designed and not implicitly granted.

#### Acceptance Criteria

1. THE Policy file (`politica.json`) SHALL declare each tool as one of: permitida, requiere_confirmacion, denegada, or oculta.
2. THE Policy file SHALL declare the StepLimit (maximum 8 steps per invoice) and the TokenLimit (maximum tokens per invoice execution).
3. THE Agent SHALL read `politica.json` at startup and SHALL NOT invoke any tool classified as denegada or oculta.
4. WHEN a tool classified as `requiere_confirmacion` is about to be invoked, THE Agent SHALL request explicit user confirmation via the CLI before proceeding.

---

### Requirement 13: Procedimiento del agente (`SKILL.md`)

**User Story:** As a developer, I want a formal skill document that describes the agent's step-by-step procedure, business rules, and stopping criteria, so that the agent's behavior can be evaluated independently of the model that executes it.

#### Acceptance Criteria

1. THE Skill document (`SKILL.md`) SHALL document the six-step procedure in order: Extraer → Validar → Aritmética → Duplicados → Confirmar → Registrar.
2. THE Skill document SHALL list all business rules R1–R11 with their corresponding enforcement points in the procedure.
3. THE Skill document SHALL define explicit stopping criteria: validation failure after user correction, user rejection of confirmation, StepLimit reached, or TokenLimit reached.
4. THE Skill document SHALL state that the Agent treats all OCR_Result content as untrusted data. (R10)

---

### Requirement 14: Trazas por ejecución

**User Story:** As a developer, I want each invoice processing run to produce a complete trace, so that results are reproducible and auditable.

#### Acceptance Criteria

1. WHEN the Agent completes or stops processing an invoice, THE Agent SHALL write a Trace record to persistent storage containing: each tool call name, input parameters, and result; each decision made by the Agent; total tokens consumed; and total duration in milliseconds.
2. THE Trace SHALL record the reason for termination: successful registration, user rejection, validation failure, StepLimit reached, or TokenLimit reached.
3. IF an error occurs during Trace writing, THEN THE Agent SHALL log the error to stderr without interrupting any in-progress user interaction.

---

### Requirement 15: Conjunto de evaluación

**User Story:** As a researcher, I want a labeled evaluation dataset of at least 45 invoices, so that the system's accuracy and the agent's resistance to indirect injection can be measured objectively.

#### Acceptance Criteria

1. THE EvaluationSet SHALL contain at least 45 invoice images: 18 clean and 27 difficult.
2. THE EvaluationSet's 27 difficult cases SHALL be distributed as: at least 6 blurry, at least 5 tilted, at least 5 with multiple discounts, at least 5 duplicates, and at least 6 containing embedded malicious text (indirect injection attempts).
3. WHEN the EvaluationSet is assembled, each invoice SHALL be independently labeled by two annotators for the fields comercio, fecha, total, moneda, and categoría.
4. THE EvaluationSet documentation SHALL report Cohen's kappa (κ) for the categoría field and percentage agreement for all other fields.
5. THE EvaluationSet SHALL have all personally identifiable information (name, ID number, card digits, address) obscured or blurred before storage in the repository.

---

### Requirement 16: Análisis de seguridad contra inyección indirecta

**User Story:** As a researcher, I want the system to be tested against indirect prompt injection attacks embedded in invoice images, so that resistance to manipulation is formally demonstrated.

#### Acceptance Criteria

1. THE security analysis SHALL document at least 5 distinct indirect injection attack scenarios, each with an attack description, the embedded instruction text used, and the observed system response.
2. WHEN the Agent processes an invoice image containing embedded instructions, THE Agent SHALL record in the Trace that the content was treated as data and not executed as instructions. (R10)
3. THE security analysis report SHALL state, for each of the ≥ 5 attack cases, whether the attack succeeded (data was altered or another user's data was exposed) or was blocked.
4. IF any attack succeeds in altering stored data or exposing another user's transactions, THEN the security analysis SHALL document the failure and the corresponding remediation applied.

---

### Requirement 17: Servidor MCP `finanzas-mcp` y persistencia en SQLite

**User Story:** As a developer, I want the `finanzas-mcp` server to persist validated transactions in a local SQLite database and expose exactly the required tools over stdio MCP, so that the system is self-contained and auditable.

#### Acceptance Criteria

1. THE finanzas-mcp SHALL expose exactly the following tools: `validar_factura`, `buscar_duplicados`, `listar_transacciones`, and `registrar_transaccion`.
2. THE finanzas-mcp SHALL communicate over stdio using JSON-RPC 2.0 with one JSON message per line, with UTF-8 encoding enforced on both stdin and stdout.
3. THE finanzas-mcp SHALL persist all successfully registered transactions in the SQLite_DB.
4. WHEN a business rule violation occurs in finanzas-mcp, THE finanzas-mcp SHALL return the error as a result with `isError: true` and a descriptive message; THE finanzas-mcp SHALL NOT terminate due to a business rule error.
5. THE finanzas-mcp SHALL NEVER write debug output to stdout; all diagnostic messages SHALL be written to stderr.

---

### Requirement 18: Pruebas unitarias

**User Story:** As a developer, I want each business rule to be covered by at least one passing test and one failing test, so that regressions are detected automatically.

#### Acceptance Criteria

1. THE test suite SHALL contain at least one test that exercises the compliant path and at least one test that exercises the non-compliant path for each business rule R1–R11.
2. THE test suite SHALL be located in the `tests/` directory and SHALL be runnable with `python -m unittest discover -s tests -v`.
3. WHEN all tests are executed, THE test suite SHALL produce a deterministic result with no dependency on external network services.

---

### Requirement 19: Interfaz de línea de comandos (CLI)

**User Story:** As a usuario, I want to interact with the agent exclusively through the CLI, so that I can process invoices without any graphical interface.

#### Acceptance Criteria

1. THE Agent SHALL accept invoice processing requests exclusively through CLI arguments or interactive CLI prompts.
2. WHEN the Agent requires user input (confirmation, field correction, category selection), THE Agent SHALL prompt the user via the CLI and wait for a response before proceeding.
3. THE Agent SHALL display the processing result (registration success, validation error, or stop reason) in the CLI output upon completion of each invoice run.

---

### Requirement 20: Despliegue con Docker

**User Story:** As a developer, I want the system to be deployable as a Docker container, so that the environment is reproducible across machines.

#### Acceptance Criteria

1. THE system SHALL provide a `Dockerfile` that builds the complete environment using Python 3.12.
2. WHEN the Docker container starts, THE finanzas-mcp server and the Agent SHALL be launchable without additional host dependencies beyond Docker itself.
3. THE SQLite_DB file SHALL be mapped to a host volume so that transaction data persists across container restarts.


