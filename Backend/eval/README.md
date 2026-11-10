# Conjunto de evaluación (EvaluationSet)

Dataset etiquetado de 45 facturas para medir la exactitud del sistema y la resistencia a inyección indirecta (Req. 15, 16).

## Composición (Req. 15.1, 15.2)

| tipo | dificultad | mínimo | filas en labels.csv |
|---|---|---|---|
| clean | (vacío) | 18 | 18 |
| difficult | blurry | 6 | 6 |
| difficult | tilted | 5 | 5 |
| difficult | discount (múltiples descuentos) | 5 | 5 |
| difficult | duplicate | 5 | 5 |
| difficult | injection (texto malicioso incrustado) | 6 | 6 |
| **Total** | | **45** | **45** |

## Estructura

- `labels.csv`: UTF-8, una fila por imagen. Las imágenes se nombran `eval_001.jpg` ... `eval_045.jpg` (marcadores de posición; actualizar `imagen` con el nombre real).
- Las imágenes se guardan en `eval/images/` (o la ruta acordada) y NO deben contener PII.

### Columnas de `labels.csv`

| Columna | Descripción |
|---|---|
| imagen | Nombre del archivo de imagen |
| comercio, fecha, total, moneda, categoria | Etiqueta final (consenso tras resolver desacuerdos) |
| tipo | `clean` o `difficult` |
| dificultad | `blurry`, `tilted`, `discount`, `duplicate`, `injection` (vacío si clean) |
| anotador_1_* / anotador_2_* | Etiquetas independientes de cada anotador para comercio, fecha, total, moneda, categoria |
| kappa_categoria | Cohen's kappa de categoría (valor global, se rellena en una fila o en el reporte) |
| acuerdo_comercio, acuerdo_fecha, acuerdo_total, acuerdo_moneda | Acuerdo porcentual por campo (valor global) |

## Criterios de etiquetado

- fecha: formato ISO `YYYY-MM-DD`.
- total: número decimal con punto, el monto final pagado (después de descuentos e impuestos).
- moneda: código ISO 4217 (CRC, USD, ...).
- comercio: nombre tal como aparece, sin sufijos legales ni sucursal.
- categoria: una de las categorías definidas en el sistema (ver `finanzas_mcp/business/categorias.py`).
- Cada anotador etiqueta de forma independiente, sin consultar al otro (Req. 15.3).
- Facturas `duplicate`: misma factura capturada dos veces; ambas se etiquetan igual.
- Facturas `injection`: se etiqueta el contenido real de la factura; el texto malicioso se ignora como dato.
- PII (nombre, cédula, dígitos de tarjeta, dirección) debe ser difuminada u ocultada antes de guardar la imagen en el repositorio (Req. 15.5).

## Cálculo de acuerdo (Req. 15.4)

Acuerdo porcentual (comercio, fecha, total, moneda), por campo:

```
acuerdo = 100 * (# filas donde anotador_1_campo == anotador_2_campo) / N
```

Comparar tras normalizar (minúsculas, espacios recortados; total como decimal).

Cohen's kappa para categoría:

```
po = proporción de coincidencias observadas
pe = sum_k (p1_k * p2_k)   # p1_k, p2_k: proporción de la categoría k para cada anotador
kappa = (po - pe) / (1 - pe)
```

Ejemplo en Python:

```python
import pandas as pd
from sklearn.metrics import cohen_kappa_score

df = pd.read_csv("eval/labels.csv", encoding="utf-8")
kappa = cohen_kappa_score(df["anotador_1_categoria"], df["anotador_2_categoria"])
for c in ["comercio", "fecha", "total", "moneda"]:
    a = df[f"anotador_1_{c}"].astype(str).str.strip().str.lower()
    b = df[f"anotador_2_{c}"].astype(str).str.strip().str.lower()
    print(c, round(100 * (a == b).mean(), 1))
print("kappa_categoria", round(kappa, 3))
```

Reportar los resultados (κ de categoría y % de acuerdo de los demás campos) en este README y en las columnas `kappa_categoria` / `acuerdo_*`.

## Resultados

| Campo | Métrica | Valor |
|---|---|---|
| categoria | Cohen's κ | _pendiente_ |
| comercio | % acuerdo | _pendiente_ |
| fecha | % acuerdo | _pendiente_ |
| total | % acuerdo | _pendiente_ |
| moneda | % acuerdo | _pendiente_ |
