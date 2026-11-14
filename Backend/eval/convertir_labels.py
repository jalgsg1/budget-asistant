# -*- coding: utf-8 -*-
"""Conversión documentada de `eval/labels.csv` a entradas de `ground_truth.json`.

`labels.csv` nunca se modifica. Uso:
    python -m eval.convertir_labels [labels.csv] [ground_truth.json]
Escribe solo el destino indicado (por defecto `ground_truth_convertido.json` junto al CSV).
"""
from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

TRADUCCION_DIFICULTAD: dict[str, str] = {
    "": "limpia",
    "clean": "limpia",
    "blurry": "borrosa",
    "tilted": "inclinada",
    "discount": "multiples_descuentos",
    "duplicate": "duplicada",
    "injection": "inyeccion",
}


def _total(valor: str) -> Any:
    texto = (valor or "").strip()
    if not texto:
        return ""
    try:
        return float(Decimal(texto).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return texto


def convertir_filas(filas: Iterable[Mapping[str, str]]) -> list[dict]:
    """Convierte cada fila del CSV a una entrada (una por fila, 100% de las filas).

    Columnas de salida: imagen, comercio, fecha, total, moneda, categoria, dificultad.
    La dificultad se traduce al vocabulario en español; las filas `injection` quedan con
    dificultad "inyeccion" para que el llamador las separe (ver `separar_inyecciones`).
    """
    salida: list[dict] = []
    for fila in filas:
        dif = (fila.get("dificultad") or "").strip().lower()
        salida.append({
            "imagen": (fila.get("imagen") or "").strip(),
            "comercio": (fila.get("comercio") or "").strip(),
            "fecha": (fila.get("fecha") or "").strip(),
            "total": _total(fila.get("total") or ""),
            "moneda": (fila.get("moneda") or "").strip().upper(),
            "categoria": (fila.get("categoria") or "").strip(),
            "dificultad": TRADUCCION_DIFICULTAD.get(dif, dif),
        })
    return salida


def separar_inyecciones(entradas: Iterable[Mapping[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Devuelve (particion_limpia, inyecciones)."""
    limpia, inyec = [], []
    for e in entradas:
        (inyec if e.get("dificultad") == "inyeccion" else limpia).append(dict(e))
    return limpia, inyec


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    origen = Path(args[0]) if args else Path(__file__).parent / "labels.csv"
    destino = Path(args[1]) if len(args) > 1 else origen.with_name("ground_truth_convertido.json")
    with open(origen, newline="", encoding="utf-8") as fh:  # solo lectura
        filas = list(csv.DictReader(fh))
    destino.write_text(
        json.dumps(convertir_filas(filas), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(filas)} filas convertidas -> {destino}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
