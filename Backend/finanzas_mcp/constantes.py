# -*- coding: utf-8 -*-
"""Constantes de dominio del paquete ``finanzas_mcp``.

Solo biblioteca estándar; no importa ``mcp`` ni otros módulos del proyecto.
"""

from __future__ import annotations

# Validación
MONEDAS_VALIDAS: frozenset[str] = frozenset({"CRC", "USD"})
CAMPOS_OBLIGATORIOS: tuple[str, ...] = (
    "comercio",
    "fecha",
    "total",
    "moneda",
    "categoria",
)

# Categorías (lista cerrada de gasto)
CATEGORIAS_CERRADAS: list[str] = [
    "Alimentación",
    "Transporte",
    "Salud",
    "Educación",
    "Entretenimiento",
    "Servicios",
    "Tecnología",
    "Ropa",
    "Hogar",
    "Viajes",
    "Restaurantes",
    "Deportes",
    "Mascotas",
    "Seguros",
    "Otros",
]

# HITL
MODOS_HITL: tuple[str, ...] = ("siempre", "adaptativo")
AUTO_TOKEN_PREFIX: str = "auto:"

CODIGO_AUTO_NO_PERMITIDO: str = "AUTOMATIC_TOKEN_NOT_ALLOWED"
CODIGO_MONTO_ALTO: str = "HIGH_AMOUNT_CONFIRMATION_REQUIRED"
CODIGO_HUMANO: str = "HUMAN_CONFIRMATION_REQUIRED"
