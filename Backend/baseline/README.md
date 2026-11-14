# baseline/

Sistemas de control del experimento: `baseline_naive` y `baseline_prompt_guarded`.
Hacen una sola llamada multimodal al LLM con una herramienta `insertar_transaccion`
que escribe directo en una BD SQLite temporal (esquema de `finanzas_mcp/db/schema.sql`).

## Exclusión de `.kiro/steering/seguridad.md`

La regla `.kiro/steering/seguridad.md` **no aplica a este directorio**. Los baselines
omiten a propósito el guardián MCP, la validación determinista y la confirmación
humana, porque son el control contra el que se mide la arquitectura propuesta.
No deben reutilizarse fuera del experimento.

## Restricciones

- Ningún módulo importa `ocr_mcp`, `finanzas_mcp.business`, `finanzas_mcp.server`,
  `mcp`, `agent` ni `api_pruebas`.
- Ninguna API recibe `UserIO`: no piden confirmación.
- Timeout de 60 s por factura; un fallo deja estado `error` sin fila parcial.

## Uso manual

```
python -m baseline.baseline_naive factura1.jpg factura2.jpg --trazas salida/
python -m baseline.baseline_prompt_guarded factura1.jpg --conservar-bd
```

Requiere `LLM_PROVIDER`, `OCR_MODEL` y la clave del proveedor.
