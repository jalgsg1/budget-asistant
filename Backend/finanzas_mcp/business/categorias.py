# -*- coding: utf-8 -*-
"""
Catálogo cerrado de categorías de gasto para gestor-facturas.

Este módulo define la lista canónica de categorías aceptadas por el sistema.
La capa de validación (validacion.py) y el agente deben importar exclusivamente
desde aquí para garantizar consistencia.

No importa `mcp`, `sys.stdin` ni `sys.stdout`.
"""

from __future__ import annotations

#: Lista cerrada de categorías de gasto (ClosedCategoryList).
#: Solo los valores presentes en esta lista son aceptados por `validar_categoria`
#: y por `registrar_transaccion` en el servidor finanzas-mcp (Requisito 7.1).
CLOSED_CATEGORY_LIST: list[str] = [
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
