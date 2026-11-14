"""Traza común a baselines y arquitectura (Req. 11.5 a 11.10)."""
from __future__ import annotations

import json
import math
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

ESTADOS_FINALES: tuple[str, ...] = ("registrada", "rechazada", "usuario_rechazo", "limite", "error")
CAMPOS: tuple[str, ...] = (
    "sistema", "ruta_factura", "tokens_entrada", "tokens_salida",
    "duracion_ms", "estado_final", "registro_en_bd",
)
_ESTADO_AGENTE = {
    "success": "registrada",
    "validation_error": "rechazada",
    "user_abort": "usuario_rechazo",
    "step_limit": "limite",
    "token_limit": "limite",
}


def _es_entero(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _es_numero(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass(frozen=True)
class TrazaComun:
    sistema: str
    ruta_factura: str
    tokens_entrada: int
    tokens_salida: int
    duracion_ms: float
    estado_final: str
    registro_en_bd: bool

    def __post_init__(self) -> None:
        if not isinstance(self.sistema, str) or not isinstance(self.ruta_factura, str):
            raise ValueError("sistema y ruta_factura deben ser texto")
        if not _es_entero(self.tokens_entrada) or self.tokens_entrada < 0:
            raise ValueError("tokens_entrada debe ser entero >= 0")
        if not _es_entero(self.tokens_salida) or self.tokens_salida < 0:
            raise ValueError("tokens_salida debe ser entero >= 0")
        if (not _es_numero(self.duracion_ms) or not math.isfinite(self.duracion_ms)
                or self.duracion_ms < 0):
            raise ValueError("duracion_ms debe ser número finito >= 0")
        if self.estado_final not in ESTADOS_FINALES:
            raise ValueError(f"estado_final debe ser uno de {ESTADOS_FINALES}")
        if not isinstance(self.registro_en_bd, bool):
            raise ValueError("registro_en_bd debe ser booleano")

    def a_dict(self) -> dict:
        return {c: getattr(self, c) for c in CAMPOS}

    @classmethod
    def desde_dict(cls, d: Mapping) -> "TrazaComun":
        if not isinstance(d, Mapping):
            raise ValueError("La traza debe ser un objeto")
        faltan = [c for c in CAMPOS if c not in d]
        sobran = [k for k in d if k not in CAMPOS]
        if faltan or sobran:
            raise ValueError(f"Campos inválidos: faltan={faltan} sobran={sobran}")
        return cls(**{c: d[c] for c in CAMPOS})


def escribir_traza(traza: TrazaComun, directorio: str) -> str | None:
    """Escribe la traza como JSON UTF-8. Ante fallo informa por stderr y devuelve None."""
    try:
        os.makedirs(directorio, exist_ok=True)
        ruta = os.path.join(directorio, f"traza_{uuid.uuid4().hex}.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(traza.a_dict(), fh, ensure_ascii=False)
        return ruta
    except Exception as exc:  # noqa: BLE001 - no debe alterar el resultado
        print(f"Error al escribir la traza común: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def desde_traza_agente(pipeline_result: Any, duracion_ms: float, registro_en_bd: bool) -> TrazaComun:
    """Convierte el resultado del pipeline del agente en una TrazaComun."""
    traza = pipeline_result.trace
    estado = _ESTADO_AGENTE.get(pipeline_result.status, "error")
    return TrazaComun(
        sistema="arquitectura_mcp",
        ruta_factura=str(traza.image_path),
        tokens_entrada=int(getattr(traza, "tokens_entrada", 0) or 0),
        tokens_salida=int(getattr(traza, "tokens_salida", 0) or 0),
        duracion_ms=float(duracion_ms),
        estado_final=estado,
        registro_en_bd=bool(registro_en_bd),
    )
