# -*- coding: utf-8 -*-
"""
api_pruebas/modo_pruebas.py — Permisos de reset/seed y datos de ejemplo.

Nunca importa ``mcp``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from api_pruebas.config import Config
from api_pruebas.errores import ErrorApi, error_api
from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST


def db_es_de_pruebas(db_path: Path, allowlist: Sequence[Path]) -> bool:
    """True si ``db_path`` es una base de datos de pruebas.

    Con ``allowlist`` no vacía es la única regla (igual a una entrada o dentro de
    una carpeta listada). Sin ella, el nombre del archivo debe contener ``test`` o
    ``prueba`` (sin distinguir mayúsculas). Las rutas se resuelven antes de comparar.
    """
    ruta = Path(db_path).resolve()
    if allowlist:
        for entrada in allowlist:
            e = Path(entrada).resolve()
            if ruta == e or e in ruta.parents:
                return True
        return False
    nombre = ruta.name.lower()
    return "test" in nombre or "prueba" in nombre


def verificar_permiso(config: Config) -> None:
    """Comprueba en orden: Modo_Pruebas y luego base permitida.

    Lanza ``ErrorApi`` 403 con ``TEST_MODE_DISABLED`` o ``TEST_DB_NOT_ALLOWED``.
    No abre la base de datos.
    """
    if not config.test_mode:
        raise error_api(
            "TEST_MODE_DISABLED",
            "El modo de pruebas está deshabilitado (API_TEST_MODE debe ser 'true').",
        )
    if not db_es_de_pruebas(config.db_path, config.test_db_allowlist):
        raise error_api(
            "TEST_DB_NOT_ALLOWED",
            "La base de datos configurada no está permitida para operaciones de prueba.",
        )


def _tx(comercio: str, fecha: str, total: float, moneda: str, categoria: str,
        descripcion: str) -> dict[str, Any]:
    return {
        "comercio": comercio,
        "fecha": fecha,
        "total": total,
        "moneda": moneda,
        "categoria": categoria,
        "descripcion": descripcion,
    }


#: Conjunto de ejemplo para ``POST /test/seed`` sin cuerpo: 5 transacciones válidas,
#: fechas pasadas fijas, CRC y USD, categorías de CLOSED_CATEGORY_LIST.
SEED_EJEMPLO: tuple[dict[str, Any], ...] = (
    _tx("Automercado", "2024-01-15", 45250.0, "CRC", "Alimentación", "Compra semanal"),
    _tx("Uber", "2024-02-03", 12.5, "USD", "Transporte", "Viaje al aeropuerto"),
    _tx("Farmacia Fischel", "2024-02-20", 8900.0, "CRC", "Salud", "Medicamentos"),
    _tx("Netflix", "2024-03-05", 15.99, "USD", "Entretenimiento", "Suscripción mensual"),
    _tx("Kölbi", "2024-03-18", 21500.0, "CRC", "Servicios", "Plan móvil"),
)

assert all(t["categoria"] in CLOSED_CATEGORY_LIST for t in SEED_EJEMPLO)


def seed_ejemplo() -> list[dict[str, Any]]:
    """Copia mutable del conjunto de ejemplo."""
    return [dict(t) for t in SEED_EJEMPLO]


__all__ = [
    "ErrorApi",
    "SEED_EJEMPLO",
    "db_es_de_pruebas",
    "seed_ejemplo",
    "verificar_permiso",
]
