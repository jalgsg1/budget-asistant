# Propuesta de proyecto — Hito 1

**Equipo:** José Andrés Lizano Gallegos
**Título provisional:** Gestion de finanzas personales: Reducción de fricción y errores de captura en facturas mediante un servidor MCP con validaciones explícitas

## 1. Problema

Una persona que paga con tarjeta o efectivo y acumula tiquetes y facturas que intenta anotar todas, pero puede que alguna se pierda antes que llegue el día de ordenar finanzas. Si bien se pueden registrar gastos a mano, en una app le toma 1–2 min por factura, así que lo abandona, y a fin de mes no sabe en qué se le fue el dinero. Entonces pueden presentar errores típicos: montos mal digitados, fechas equivocadas, gastos duplicados y moneda incorrecta como colones y dólares.

## 2. Por qué un agente

Lectura y nivel de condianza de cada factura. Esto no se puede fijar de antemano. Si un campo sale con baja confianza, el agente decide si reintentar o preguntar al usuario; si hay un posible duplicado, decide consultar antes de guardar; si la categoría es ambigua, propone opciones; y si la imagen contiene texto con instrucciones, debe tratarlo como dato y no obedecerlo. Una factura limpia se resuelve en 3 pasos; una borrosa, duplicada o maliciosa necesita otros, en otro orden.

## 3. Datos

¿De dónde salen?

Fotos tomadas por el equipo de facturas y tiquetes propios (supermercado, gasolina, restaurantes, farmacias), complementadas con imágenes de los datasets públicos CORD y SROIE si faltan casos. Las facturas duplicadas y maliciosas se construyen a partir de ellas. Puede incluir archivos .jpg

¿Cuántos casos esperan tener? 
Se esperan al menos 45 facturas:
- 31 limpias (70 %)
- 14 difíciles (60 %): 12 inclinadas y arrugadas, 1 contexto malicioso y 2 invalidas con textos maliciosos. 

+ Dos personas etiquetan cada una por separado (comercio, fecha, total, moneda, categoría); se reporta κ de Cohen para categoría y % de acuerdo para los demás campos.

¿Contienen datos personales? ¿Cómo los anonimizarán?

Sí: Nombre y cédula del receptor, talvez últimos dígitos de tarjeta, dirección. Se tapan o difuminan en la imagen antes de guardarla en el repositorio; las etiquetas no incluyen esos campos.

¿Tienen permiso para usarlos?

Las facturas serían propias o del dataset, que dan su consentimiento. CORD (CC BY 4.0) y SROIE (publicado para investigación) permiten uso académico. |

## 4. Herramientas MCP previstas

| Servidor | Herramienta | Lee o escribe | Qué valida el servidor |

|---|---|---|---|
| `ocr-mcp` | `ocr_imagen(ruta)` | Lee | Ruta solo dentro de la carpeta de facturas, tipo y tamaño de imagen; devuelve el texto envuelto como *contenido no confiable*. |

| `finanzas-mcp` (propio) | `validar_factura(datos)` | Lee | Esquema de campos obligatorios, fecha válida y no futura, moneda ISO 4217 (CRC/USD). |

| `finanzas-mcp` (propio) | `buscar_duplicados(comercio, fecha, total)` | Lee | Solo consulta la cuenta del usuario activo; máximo 10 resultados (impide "devuelve todas las facturas"). |

| `finanzas-mcp` (propio) | `listar_transacciones(filtros)` | Lee | Filtros en lista blanca, rango de fechas máximo, sin acceso a otras cuentas. |

| `finanzas-mcp` (propio) | `registrar_transaccion(...)` | **Escribe** | Revalida todo lo de `validar_factura` sin confiar en el agente, categoría en lista cerrada, rechaza duplicados, monto mayor a un umbral exige confirmación, requiere token de confirmación del usuario. |

**Política de permisos:** lectura permitida; `registrar_transaccion` solo con confirmación del usuario; borrar o editar transacciones existentes queda oculto. Límite de 8 pasos y de tokens por factura.

**Fuera de alcance (por tiempo):** app móvil, ingresos y gastos fijos. La interfaz grafica en "react native"; el foco es el agente, el MCP y el experimento.


## 5. Pregunta de investigación

**Nuestra pregunta:** ¿Mejora una Skill procedimental (extraer → validar campos obligatorios → detectar duplicados → confirmar → registrar) con validación en el servidor MCP la exactitud del registro de facturas y la resistencia a inyecciones indirectas, frente a OCR + LLM con un solo prompt?

**Condición B contra la que comparamos:** el mismo OCR y el mismo LLM con un prompt único que devuelve el JSON de la factura y lo guarda directamente, sin Skill ni herramientas de validación. Ambas condiciones se ejecutan sobre las mismas 45 facturas, con trazas de cada ejecución. Sin dejar de lado el costo en tokens y tiempo.

## 6. Cómo sabremos si funcionó

**Métrica principal:** exactitud por factura = facturas con comercio, fecha, total (±0,01) y moneda correctos ÷ total de facturas, comparada con las etiquetas consensuadas. **Éxito, definido antes de ver resultados:** la propuesta supera a la línea base en al menos 10 puntos porcentuales (prueba de McNemar sobre pares, p < 0,05) y ninguno de los ≥ 6 ataques logra registrar un dato alterado ni exponer otras facturas. **Secundarias:** exactitud por campo y de categoría, % de duplicados detectados, tokens, duración y pasos por factura (aceptamos hasta el doble de tokens).


## 7. Riesgos

- **Falta de tiempo / alcance excesivo:** se recorta a CLI, sin app móvil ni ingresos; las 45 facturas se fotografían y etiquetan en la primera semana.
- **OCR de mala calidad:** se prueba Tesseract y PaddleOCR; si ninguno sirve, se usa un LLM con visión en ambas condiciones por igual.
- **Costo o acceso a la API:** se usa un modelo pequeño, límite de tokens por caso y caché de resultados de OCR.
- **Pocas facturas propias difíciles:** se completan con CORD/SROIE y con degradaciones controladas (desenfoque, rotación).


## 8. No negociables
- **Sevidor MCP propio**: Al menos 3 tools, de esas, al menos 1 de escritura con validación del lado del servidor. Defensa en profundidad: El servidor no confía en el agente.
- **Skill**: Un SKILL.md con procedimiento, reglas y criterio de parada. Separar el criterio del modelo que lo ejecuta.
- **Archivo de politicas**: Un 'politica.json' Que indique herramientas permitidas, con confirmación, denegadas u ocultas; límites de pasos y tokens. La autonomía se diseña, no se concede.
- **Trazas**: Una traza por ejecución con cada llamada, decisión, tokens y duración. Sin trazas no hay resultados reproducibles.
- **Conjunto de evaluación**: 40 casos o más, al menos 30% difíciles, etiquetados por dos personas con acuerdo reportado. Es el juez del experimento.
- **Análisis de seguridad**: Al menos 5 ataques de inyección indirecta y su resultado. Para evitar que si un agente que lee contenido de terceros es atacable.



