# -*- coding: utf-8 -*-
"""Conversión documentada de `eval/labels.csv` a los archivos de la partición limpia.

`labels.csv` nunca se modifica. Uso:
    python -m eval.convertir_labels [labels.csv] [ground_truth.json]

Escribe, en el directorio del destino indicado:
  * `ground_truth.json` (o el nombre dado): consenso de las columnas iniciales.
  * `anotaciones_anotador_1.json` y `anotaciones_anotador_2.json`: lo que cada anotador
    registró en las columnas `anotador_<n>_*`, sin aplicar valores por defecto.

Por defecto el destino es `ground_truth_convertido.json` junto al CSV. Para generar los
archivos listos para validar, pase `eval/golden_set/clean_manual/ground_truth.json`.

Valores por defecto del consenso: `comercio` vacío -> "N/A"; `fecha` vacía -> fecha de hoy;
`moneda` vacía -> "CRC".
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from eval.constantes import (  # noqa: F401
    CAMPOS_ANOTACION,
    COMERCIO_VACIO,
    MONEDA_POR_DEFECTO,
    RESULTADO_NO_REGISTRAR,
    RESULTADO_REGISTRAR,
    TRADUCCION_DIFICULTAD,
)


def _total(valor: str) -> Any:
    texto = (valor or "").strip()
    if not texto:
        return ""
    try:
        return float(Decimal(texto).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return texto


def convertir_filas(filas: Iterable[Mapping[str, str]], hoy: date | None = None) -> list[dict]:
    """Convierte cada fila del CSV a una entrada (una por fila, 100% de las filas).

    Columnas de salida: imagen, comercio, fecha, total, moneda, categoria, dificultad,
    resultado_esperado ("registrar" si la columna del CSV falta o está vacía; "no_registrar"
    marca una factura que el sistema debe rechazar y no recibe valores por defecto).
    La dificultad se traduce al vocabulario en español (las filas `injection` quedan con
    dificultad "inyeccion"). Un `comercio` vacío se escribe como "N/A" y una `fecha` vacía
    como la fecha de hoy (`hoy`, por defecto `date.today()`). Una `moneda` vacía se escribe "CRC".
    """
    fecha_defecto = (hoy or date.today()).isoformat()
    salida: list[dict] = []
    for fila in filas:
        dif = (fila.get("dificultad") or "").strip().lower()
        resultado = (fila.get("resultado_esperado") or "").strip().lower() or RESULTADO_REGISTRAR
        # Una factura que debe rechazarse conserva los valores tal como vienen: no se usan.
        rechazo = resultado == RESULTADO_NO_REGISTRAR
        comercio = (fila.get("comercio") or "").strip()
        fecha = (fila.get("fecha") or "").strip()
        moneda = (fila.get("moneda") or "").strip().upper()
        salida.append({
            "imagen": (fila.get("imagen") or "").strip(),
            "comercio": comercio if rechazo else comercio or COMERCIO_VACIO,
            "fecha": fecha if rechazo else fecha or fecha_defecto,
            "total": _total(fila.get("total") or ""),
            "moneda": moneda if rechazo else moneda or MONEDA_POR_DEFECTO,
            "categoria": (fila.get("categoria") or "").strip(),
            "dificultad": TRADUCCION_DIFICULTAD.get(dif, dif),
            "resultado_esperado": resultado,
        })
    return salida


def convertir_anotaciones(filas: Iterable[Mapping[str, str]], anotador: int) -> list[dict]:
    """Registro independiente de un anotador (1 o 2): una entrada por fila, sin valores por defecto."""
    salida: list[dict] = []
    for fila in filas:
        entrada: dict[str, Any] = {"imagen": (fila.get("imagen") or "").strip()}
        for campo in CAMPOS_ANOTACION:
            valor = fila.get(f"anotador_{anotador}_{campo}") or ""
            entrada[campo] = _total(valor) if campo == "total" else valor.strip()
        salida.append(entrada)
    return salida


def separar_inyecciones(entradas: Iterable[Mapping[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Devuelve (particion_limpia, inyecciones)."""
    limpia, inyec = [], []
    for e in entradas:
        (inyec if e.get("dificultad") == "inyeccion" else limpia).append(dict(e))
    return limpia, inyec


def _escribir_json(ruta: Path, datos: list[dict]) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    origen = Path(args[0]) if args else Path(__file__).parent / "labels.csv"
    destino = Path(args[1]) if len(args) > 1 else origen.with_name("ground_truth_convertido.json")
    with open(origen, newline="", encoding="utf-8") as fh:  # solo lectura
        filas = list(csv.DictReader(fh))
    destino.parent.mkdir(parents=True, exist_ok=True)
    _escribir_json(destino, convertir_filas(filas))
    for n in (1, 2):
        _escribir_json(destino.with_name(f"anotaciones_anotador_{n}.json"), convertir_anotaciones(filas, n))
    print(f"{len(filas)} filas convertidas -> {destino} (+ anotaciones_anotador_1/2.json)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
