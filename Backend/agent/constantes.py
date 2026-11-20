# -*- coding: utf-8 -*-
"""Constantes de dominio del paquete ``agent``.

Solo importa la biblioteca estándar y ``finanzas_mcp.constantes``.
"""

from __future__ import annotations

from finanzas_mcp.constantes import AUTO_TOKEN_PREFIX  # noqa: F401

# HITL
ALERTAS: tuple[str, ...] = (
    "LOW_OCR_CONFIDENCE",
    "HIGH_AMOUNT",
    "POSSIBLE_DUPLICATE",
    "SUSPICIOUS_CONTENT",
)
CAMPOS_REQUERIDOS: tuple[str, ...] = ("comercio", "fecha", "total", "moneda")

MAX_REGLAS: int = 50
MAX_LONGITUD_REGLA: int = 100
MAX_LONGITUD_RAZON: int = 500

RAZON_SIEMPRE: str = "modo_hitl=siempre"
RAZON_LIMPIA: str = "Factura_Limpia: ninguna Alerta_HITL aplica."

# Subcadenas que usa api_pruebas.batch.AutoConfirmIO para responder.
PROMPT_REGISTRAR: str = "token de confirmación para registrar"
PROMPT_MONTO_ALTO: str = "token de confirmación de monto alto"
PROMPT_DUPLICADOS: str = "Posibles duplicados"
PROMPT_ALERTAS: str = "Alertas HITL"

# Contenido sospechoso
CATEGORIAS_CONTENIDO_SOSPECHOSO: tuple[str, ...] = (
    "verbo_instruccion",
    "override_rol",
    "ignorar_instrucciones",
    "datos_otros_usuarios",
    "payload_codificado",
)
MAX_CARACTERES: int = 20_000

# Estados del pipeline
ESTADO_EXITO: str = "success"
ESTADO_ERROR_VALIDACION: str = "validation_error"
ESTADO_ABORTO_USUARIO: str = "user_abort"
ESTADO_LIMITE_PASOS: str = "step_limit"
ESTADO_LIMITE_TOKENS: str = "token_limit"
ESTADOS_PIPELINE: tuple[str, ...] = (
    ESTADO_EXITO,
    ESTADO_ERROR_VALIDACION,
    ESTADO_LIMITE_PASOS,
    ESTADO_LIMITE_TOKENS,
    ESTADO_ABORTO_USUARIO,
)

# Razones de terminación
RAZON_EXITO: str = "success"
RAZON_FALLO_VALIDACION: str = "validation_failure"
RAZON_LIMITE_PASOS: str = "step_limit"
RAZON_LIMITE_TOKENS: str = "token_limit"
RAZON_RECHAZO_USUARIO: str = "user_rejection"
RAZONES_PIPELINE: tuple[str, ...] = (
    RAZON_EXITO,
    RAZON_FALLO_VALIDACION,
    RAZON_LIMITE_PASOS,
    RAZON_LIMITE_TOKENS,
    RAZON_RECHAZO_USUARIO,
)

# Campos de la transacción
REQUIRED_FIELDS: tuple[str, ...] = ("comercio", "fecha", "total", "moneda", "categoria")
OPTIONAL_FIELDS: tuple[str, ...] = ("subtotal", "iva", "descripcion")
ALLOWED_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS
OCR_REQUIRED_FIELDS: tuple[str, ...] = ("comercio", "fecha", "total", "moneda")
