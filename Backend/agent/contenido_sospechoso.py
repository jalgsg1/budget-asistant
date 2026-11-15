"""Catálogo único de patrones de contenido sospechoso y escáner determinista.

El texto escaneado se trata solo como dato; nunca se ejecuta (Req. 7.5, 7.7).
Todas las regex usan clases y repeticiones acotadas, sin cuantificadores anidados.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agent.constantes import CATEGORIAS_CONTENIDO_SOSPECHOSO, MAX_CARACTERES

CATEGORIAS: tuple[str, ...] = CATEGORIAS_CONTENIDO_SOSPECHOSO


@dataclass(frozen=True)
class PatronSospechoso:
    id: str
    categoria: str
    regex: "re.Pattern[str]"


def _p(id_: str, categoria: str, expr: str) -> PatronSospechoso:
    return PatronSospechoso(id_, categoria, re.compile(expr, re.IGNORECASE))


PATRONES: tuple[PatronSospechoso, ...] = (
    # Verbos de instrucción dirigidos al sistema
    _p("VER-001", "verbo_instruccion", r"\b(?:transfer|exfiltrate|reveal)\b"),
    _p("VER-002", "verbo_instruccion", r"\b(?:drop|delete|insert|update)\s{1,10}\w{0,50}\s{0,10}(?:table|from|into)\b"),
    _p("VER-003", "verbo_instruccion", r"\bselect\b[^\n]{1,200}\bfrom\b"),
    # Órdenes para saltarse la confirmación o la validación (en inglés y en español)
    _p("VER-004", "verbo_instruccion",
       r"\b(?:do\s{1,10}not|don't|never)\s{1,10}(?:ask|request|require|seek)\b[^\n]{0,30}\bconfirm"
       r"|\bno\s{1,10}(?:pidas|solicites|requieras|exijas)\b[^\n]{0,30}\bconfirm"),
    _p("VER-005", "verbo_instruccion",
       r"\b(?:skip|bypass|omit|omite|omitir|saltar|salta|evita|evitar)\b[^\n]{0,30}"
       r"\b(?:confirmation|confirmaci[oó]n|validation|validaci[oó]n|verification|verificaci[oó]n)\b"),
    # Marcadores de cambio de rol
    _p("ROL-001", "override_rol", r"\bsystem\s{0,10}:"),
    _p("ROL-002", "override_rol", r"\b(?:assistant|developer)\s{0,10}:"),
    _p("ROL-003", "override_rol", r"\bsystem\s{1,10}(?:note|notice|message|prompt|instructions?|override)\b"),
    _p("ROL-004", "override_rol",
       r"\b(?:you\s{1,10}are\s{1,10}(?:no\s{1,10}longer|now)\s{1,10}(?:a|an|the|my|in|your)"
       r"|ahora\s{1,10}eres\s{1,10}(?:un|una|el|la|mi|admin\w{0,10}|root))\b"),
    _p("ROL-005", "override_rol",
       r"\b(?:note|nota|message|mensaje)\s{1,10}(?:to|for|para)\s{1,10}(?:the\s{1,10}|el\s{1,10})?"
       r"(?:assistant|asistente|model|modelo|system|sistema)\b"),
    # Ignorar instrucciones previas
    _p("IGN-001", "ignorar_instrucciones", r"ignore\s{1,10}(?:all\s{1,10})?(?:previous|prior)\s{1,10}instructions"),
    _p("IGN-002", "ignorar_instrucciones", r"ignora\s{1,10}(?:las\s{1,10})?instrucciones"),
    _p("IGN-003", "ignorar_instrucciones",
       r"\b(?:ignore|disregard|forget|override)\s{1,10}"
       r"(?:the|all|any|this|that|these|those|your|every|previous|prior|above|earlier)\b"),
    _p("IGN-004", "ignorar_instrucciones",
       r"\b(?:ignora|desestima|omite|olvida)\s{1,10}"
       r"(?:el|la|los|las|lo|todo|todos|todas|cualquier|esto|esta|tus)\b"),
    # Referencias a datos de otros usuarios
    _p("USR-001", "datos_otros_usuarios", r"\b(?:other|another|all)\s{1,10}users?\b[^\n]{0,40}\b(?:data|transactions?|invoices?)\b"),
    _p("USR-002", "datos_otros_usuarios", r"\b(?:otros?|todos\s{1,10}los)\s{1,10}usuarios?\b[^\n]{0,40}\b(?:datos|transacciones|facturas)\b"),
    _p("USR-003", "datos_otros_usuarios", r"\buser_id\s{0,10}[=:]"),
    # Mismo tema en el orden inverso: "transacciones de los demás usuarios"
    _p("USR-004", "datos_otros_usuarios",
       r"\b(?:transactions?|invoices?|data)\b[^\n]{0,20}\b(?:of|from)\s{1,10}(?:the\s{1,10})?"
       r"(?:all\s{1,10})?(?:other|another|all)\s{1,10}users?\b"),
    _p("USR-005", "datos_otros_usuarios",
       r"\b(?:transacciones|facturas|datos)\b[^\n]{0,20}\b(?:de|del)\s{1,10}(?:los\s{1,10})?"
       r"(?:otros|dem[aá]s|todos\s{1,10}los(?:\s{1,10}dem[aá]s)?)\s{1,10}usuarios?\b"),
    # Payload codificado (patrón base64 original conservado)
    _p("COD-001", "payload_codificado", r"[A-Za-z0-9+/]{40,}={0,2}"),
)


@dataclass(frozen=True)
class ResultadoEscaneo:
    sospechoso: bool
    ids: tuple[str, ...]
    motivo_fallo: str | None


def escanear(texto: object) -> ResultadoEscaneo:
    """Escanea `texto` contra PATRONES. Pura y determinista."""
    try:
        if not isinstance(texto, str) or not texto.strip():
            return ResultadoEscaneo(True, (), "texto_vacio")
        excede = len(texto) > MAX_CARACTERES
        muestra = texto[:MAX_CARACTERES]
        ids = tuple(p.id for p in PATRONES if p.regex.search(muestra))
        if excede:
            return ResultadoEscaneo(True, ids, "texto_excede_limite")
        return ResultadoEscaneo(bool(ids), ids, None)
    except Exception:
        return ResultadoEscaneo(True, (), "error_escaneo")
