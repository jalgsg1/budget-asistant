"""Modelo de datos de la tabla ``transactions`` (sin dependencias de mcp/finanzas_mcp)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

COLUMNAS = (
    "id", "user_id", "comercio", "fecha", "total", "moneda",
    "categoria", "subtotal", "iva", "descripcion", "created_at",
)

_OBLIGATORIAS = ("user_id", "comercio", "fecha", "total", "moneda", "categoria")
_OPCIONALES = ("id", "subtotal", "iva", "descripcion", "created_at")


@dataclass
class Transaction:
    user_id: str
    comercio: str
    fecha: str
    total: float
    moneda: str
    categoria: str
    subtotal: Optional[float] = None
    iva: Optional[float] = None
    descripcion: Optional[str] = None
    created_at: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | Sequence[Any]) -> "Transaction":
        """Construye desde sqlite3.Row/dict (por nombre) o tupla en el orden de COLUMNAS.

        Lanza KeyError si falta una columna obligatoria en una fila por nombre, y
        ValueError si una tupla no tiene la longitud de COLUMNAS.
        """
        if hasattr(row, "keys"):
            nombres = set(row.keys())
            faltantes = [c for c in _OBLIGATORIAS if c not in nombres]
            if faltantes:
                raise KeyError(f"Columnas obligatorias ausentes: {', '.join(faltantes)}")
            datos = {c: row[c] for c in COLUMNAS if c in nombres}
        else:
            valores = tuple(row)
            if len(valores) != len(COLUMNAS):
                raise ValueError(
                    f"La fila tiene {len(valores)} valores; se esperaban {len(COLUMNAS)}"
                )
            datos = dict(zip(COLUMNAS, valores))
        return cls(**datos)

    def to_dict(self) -> dict[str, Any]:
        """Diccionario con las claves de COLUMNAS."""
        d = asdict(self)
        return {c: d[c] for c in COLUMNAS}
