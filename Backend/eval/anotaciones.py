# -*- coding: utf-8 -*-
"""Acuerdo entre anotadores: porcentaje de acuerdo y kappa de Cohen (funciones puras)."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Mapping, Sequence

from eval.constantes import CAMPOS_ACUERDO  # noqa: F401


def _normalizar(valor: Any, numerico: bool = False) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    if numerico and texto:
        try:
            return str(Decimal(texto).quantize(Decimal("0.01")))
        except (InvalidOperation, ValueError):
            pass
    return texto.lower()


def _redondear(f: Fraction, dec: int) -> float:
    return round(float(f), dec)


def acuerdo_porcentual(a: Sequence[Any], b: Sequence[Any], numerico: bool = False) -> float | None:
    """100 * coincidencias / n tras normalizar (minúsculas, strip; numérico a 2 decimales).

    Redondeado a 2 decimales. None si n == 0.
    """
    if len(a) != len(b):
        raise ValueError("Las listas deben tener la misma longitud")
    n = len(a)
    if n == 0:
        return None
    coinc = sum(1 for x, y in zip(a, b) if _normalizar(x, numerico) == _normalizar(y, numerico))
    return round(100.0 * coinc / n, 2)


def kappa_cohen(a: Sequence[Any], b: Sequence[Any]) -> float | None:
    """kappa = (po - pe) / (1 - pe), a 4 decimales. None si n == 0 o pe == 1."""
    if len(a) != len(b):
        raise ValueError("Las listas deben tener la misma longitud")
    n = len(a)
    if n == 0:
        return None
    na = [_normalizar(x) for x in a]
    nb = [_normalizar(y) for y in b]
    po = Fraction(sum(1 for x, y in zip(na, nb) if x == y), n)
    ca, cb = Counter(na), Counter(nb)
    pe = sum(Fraction(ca[k], n) * Fraction(cb[k], n) for k in set(ca) | set(cb))
    if pe == 1:
        return None
    return _redondear((po - pe) / (1 - pe), 4)


def resumen_acuerdos(ann1: Sequence[Mapping[str, Any]], ann2: Sequence[Mapping[str, Any]]) -> dict:
    """Resumen de acuerdos sobre las imágenes presentes en ambas anotaciones (por `imagen`).

    Devuelve `kappa_categoria` (None si indefinido), `kappa_categoria_indefinido`,
    `acuerdo_categoria` y `acuerdo_<campo>` para cada campo en CAMPOS_ACUERDO.
    """
    m1 = {str(e.get("imagen")): e for e in ann1}
    m2 = {str(e.get("imagen")): e for e in ann2}
    comunes = sorted(set(m1) & set(m2))
    cat1 = [m1[i].get("categoria") for i in comunes]
    cat2 = [m2[i].get("categoria") for i in comunes]
    kappa = kappa_cohen(cat1, cat2)
    res: dict = {
        "n_imagenes": len(comunes),
        "kappa_categoria": kappa,
        "kappa_categoria_indefinido": kappa is None,
        "acuerdo_categoria": acuerdo_porcentual(cat1, cat2),
    }
    for campo in CAMPOS_ACUERDO:
        v1 = [m1[i].get(campo) for i in comunes]
        v2 = [m2[i].get(campo) for i in comunes]
        res[f"acuerdo_{campo}"] = acuerdo_porcentual(v1, v2, numerico=campo in ("total", "subtotal", "iva"))
    return res
