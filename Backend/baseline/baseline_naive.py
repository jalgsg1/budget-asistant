# -*- coding: utf-8 -*-
"""Baseline naive: el LLM escribe directo en SQLite, sin validación (Req. 9)."""
from __future__ import annotations

import sys
from typing import Sequence

from baseline._comun import main_baseline
from baseline.constantes import SISTEMA_NAIVE

NOMBRE = SISTEMA_NAIVE

SYSTEM_PROMPT_NAIVE = (
    "Extrae los campos de la factura (comercio, fecha, total, moneda, categoria, "
    "subtotal, iva, descripcion) y llama a la herramienta insertar_transaccion."
)


def main(argv: Sequence[str] | None = None) -> int:
    return main_baseline(NOMBRE, SYSTEM_PROMPT_NAIVE, argv)


if __name__ == "__main__":
    sys.exit(main())
