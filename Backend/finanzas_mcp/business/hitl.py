# -*- coding: utf-8 -*-
"""Parámetros HITL, token automático y prioridad de rechazo (lógica pura).

Sin dependencia de ``mcp``: lo usan tanto el agente como el servidor
``finanzas-mcp``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

MODOS_HITL: tuple[str, ...] = ("siempre", "adaptativo")
AUTO_TOKEN_PREFIX: str = "auto:"

CODIGO_AUTO_NO_PERMITIDO: str = "AUTOMATIC_TOKEN_NOT_ALLOWED"
CODIGO_MONTO_ALTO: str = "HIGH_AMOUNT_CONFIRMATION_REQUIRED"
CODIGO_HUMANO: str = "HUMAN_CONFIRMATION_REQUIRED"


class PoliticaHitlError(ValueError):
    """Parámetro HITL inválido; el mensaje nombra el parámetro y los valores aceptados."""


@dataclass(frozen=True)
class ParametrosHitl:
    modo_hitl: str
    umbral_confianza_ocr: float


def _resolver_modo(raw: Mapping[str, Any]) -> str:
    if "modo_hitl" not in raw:
        return "siempre"
    modo = raw["modo_hitl"]
    if not isinstance(modo, str) or modo not in MODOS_HITL:
        raise PoliticaHitlError(
            f"modo_hitl inválido: {modo!r}. Valores aceptados: "
            + ", ".join(f'"{m}"' for m in MODOS_HITL)
        )
    return modo


def _resolver_umbral(raw: Mapping[str, Any], exigir_umbral: bool) -> float:
    if "umbral_confianza_ocr" not in raw:
        if exigir_umbral:
            raise PoliticaHitlError(
                "umbral_confianza_ocr es obligatorio (número entre 0.0 y 1.0)"
            )
        return 1.0
    valor = raw["umbral_confianza_ocr"]
    if (
        isinstance(valor, bool)
        or not isinstance(valor, (int, float))
        or not math.isfinite(valor)
        or not 0.0 <= valor <= 1.0
    ):
        raise PoliticaHitlError(
            f"umbral_confianza_ocr inválido: {valor!r}. Debe ser un número finito entre 0.0 y 1.0"
        )
    return float(valor)


def resolver_parametros_hitl(
    raw: Mapping[str, Any], exigir_umbral: bool = True
) -> ParametrosHitl:
    """Valida ``modo_hitl`` y ``umbral_confianza_ocr`` de una política cruda.

    ``modo_hitl`` ausente -> ``"siempre"``. Con ``exigir_umbral=False`` un
    umbral ausente da 1.0 (falla cerrada); un umbral presente se valida siempre.
    """
    return ParametrosHitl(
        modo_hitl=_resolver_modo(raw),
        umbral_confianza_ocr=_resolver_umbral(raw, exigir_umbral),
    )


def es_token_automatico(token: object) -> bool:
    """True si ``token`` es ``str`` y, sin espacios laterales, empieza por ``auto:``."""
    return isinstance(token, str) and token.strip().startswith(AUTO_TOKEN_PREFIX)


def decidir_rechazo_automatico(
    monto_alto: bool,
    aritmetica_invalida: bool,
    duplicado: bool,
    confianza_baja_o_ausente: bool,
    contenido_sospechoso_o_ausente: bool,
) -> Optional[str]:
    """Código de rechazo para un token automático, o ``None`` si se acepta.

    El monto alto tiene prioridad; cualquier otra condición da el código humano.
    """
    if monto_alto:
        return CODIGO_MONTO_ALTO
    if (
        aritmetica_invalida
        or duplicado
        or confianza_baja_o_ausente
        or contenido_sospechoso_o_ausente
    ):
        return CODIGO_HUMANO
    return None
