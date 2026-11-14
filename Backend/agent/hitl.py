"""Alertas HITL, decisión HITL y token automático (lógica pura, sin E/S).

Requisitos: 4.3, 5.1-5.8, 8.1-8.4 de la spec evaluacion-experimental-paper.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

ALERTAS: tuple[str, ...] = (
    "LOW_OCR_CONFIDENCE",
    "HIGH_AMOUNT",
    "ARITHMETIC_MISMATCH",
    "POSSIBLE_DUPLICATE",
    "SUSPICIOUS_CONTENT",
)

AUTO_TOKEN_PREFIX = "auto:"
CAMPOS_REQUERIDOS: tuple[str, ...] = ("comercio", "fecha", "total", "moneda")

MAX_REGLAS = 50
MAX_LONGITUD_REGLA = 100
MAX_LONGITUD_RAZON = 500

RAZON_SIEMPRE = "modo_hitl=siempre"
RAZON_LIMPIA = "Factura_Limpia: ninguna Alerta_HITL aplica."

# Subcadenas que usa api_pruebas.batch.AutoConfirmIO para responder.
PROMPT_REGISTRAR = "token de confirmación para registrar"
PROMPT_MONTO_ALTO = "token de confirmación de monto alto"
PROMPT_DUPLICADOS = "Posibles duplicados"
PROMPT_ALERTAS = "Alertas HITL"


@dataclass(frozen=True)
class EntradaAlertas:
    confianza_global: Optional[float]
    confianza_campos: Mapping[str, float]
    ocr_bajo_legado: bool
    umbral_confianza_ocr: float
    total: Optional[float]
    moneda: Optional[str]
    umbrales_monto: Mapping[str, float]
    subtotal_extraido: Optional[float]
    iva_extraido: Optional[float]
    total_extraido: Optional[float]
    n_duplicados: int
    contenido_sospechoso: bool


def _confianza_baja(e: EntradaAlertas) -> bool:
    if e.ocr_bajo_legado:
        return True
    u = e.umbral_confianza_ocr
    if e.confianza_global is not None and e.confianza_global < u:
        return True
    for campo in CAMPOS_REQUERIDOS:
        valor = e.confianza_campos.get(campo)
        if valor is not None and valor < u:
            return True
    return False


def _monto_alto(e: EntradaAlertas) -> bool:
    if e.total is None or e.moneda is None:
        return False
    umbral = e.umbrales_monto.get(e.moneda)
    return umbral is not None and e.total > umbral


def _aritmetica_invalida(e: EntradaAlertas) -> bool:
    if e.subtotal_extraido is None or e.iva_extraido is None or e.total_extraido is None:
        return False
    return round(abs(e.subtotal_extraido + e.iva_extraido - e.total_extraido), 2) > 0.01


def evaluar_alertas(e: EntradaAlertas) -> tuple[str, ...]:
    """Alertas aplicables, siempre en el orden de ``ALERTAS``."""
    aplica = {
        "LOW_OCR_CONFIDENCE": _confianza_baja(e),
        "HIGH_AMOUNT": _monto_alto(e),
        "ARITHMETIC_MISMATCH": _aritmetica_invalida(e),
        "POSSIBLE_DUPLICATE": e.n_duplicados > 0,
        "SUSPICIOUS_CONTENT": bool(e.contenido_sospechoso),
    }
    return tuple(a for a in ALERTAS if aplica[a])


@dataclass(frozen=True)
class DecisionHitl:
    hitl_solicitado: bool
    modo_hitl: str
    reglas_detonantes: tuple[str, ...]
    razon: str

    def a_dict(self) -> dict:
        return {
            "hitl_solicitado": self.hitl_solicitado,
            "modo_hitl": self.modo_hitl,
            "reglas_detonantes": list(self.reglas_detonantes),
            "razon": self.razon,
        }


def _limpiar_reglas(reglas: Sequence[str]) -> tuple[str, ...]:
    """Aplica los límites de 8.1: hasta 50 ítems no vacíos de 1 a 100 caracteres."""
    salida: list[str] = []
    for r in reglas:
        texto = str(r)[:MAX_LONGITUD_REGLA]
        if texto:
            salida.append(texto)
        if len(salida) >= MAX_REGLAS:
            break
    return tuple(salida)


def _acotar_razon(razon: str) -> str:
    razon = razon[:MAX_LONGITUD_RAZON]
    return razon if razon else RAZON_LIMPIA


def decidir_hitl(modo: str, alertas: Sequence[str]) -> DecisionHitl:
    reglas = _limpiar_reglas(alertas)
    if modo == "siempre":
        return DecisionHitl(True, modo, reglas, RAZON_SIEMPRE)
    if not reglas:
        return DecisionHitl(False, modo, (), RAZON_LIMPIA)
    razon = _acotar_razon("Alertas HITL aplicables: " + ", ".join(reglas) + ".")
    return DecisionHitl(True, modo, reglas, razon)


def generar_token_automatico() -> str:
    return AUTO_TOKEN_PREFIX + uuid.uuid4().hex


def clasificar_prompt(prompt: str) -> Optional[str]:
    """'monto_alto' | 'alertas' | 'registrar' | 'duplicados' o ``None`` (aclaraciones)."""
    if not isinstance(prompt, str):
        return None
    if PROMPT_MONTO_ALTO in prompt:
        return "monto_alto"
    if PROMPT_ALERTAS in prompt:
        return "alertas"
    if PROMPT_REGISTRAR in prompt:
        return "registrar"
    if prompt.startswith(PROMPT_DUPLICADOS):
        return "duplicados"
    return None
