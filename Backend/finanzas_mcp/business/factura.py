"""
finanzas_mcp/business/factura.py — Evaluación agregada de una factura (R1, R2, R3, R4, R6).

Sin dependencia de `mcp`. Aplica las reglas en el mismo orden y con las mismas
condiciones que el handler `validar_factura` del servidor MCP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.business.validacion import (
    validar_aritmetica,
    validar_campos_obligatorios,
    validar_categoria,
    validar_fecha,
    validar_moneda,
)


@dataclass
class ReglaFallida:
    """Resultado de una regla que no se cumplió."""

    regla: str
    valid: bool
    code: str | None
    message: str


@dataclass
class ResultadoFactura:
    """Resultado agregado de evaluar una factura."""

    reglas: list[ReglaFallida] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.reglas

    @property
    def errors(self) -> list[str]:
        """Todos los mensajes de error, en orden de evaluación."""
        return [r.message for r in self.reglas]

    @property
    def first_error_code(self) -> str | None:
        for r in self.reglas:
            if r.code:
                return r.code
        return None


def evaluar_factura(datos: dict) -> ResultadoFactura:
    """Evalúa R1, R2, R3, R4 y R6 y devuelve todas las reglas fallidas."""
    reglas: list[ReglaFallida] = []

    def _anotar(nombre: str, res) -> None:
        if not res.is_valid:
            for msg in res.errors:
                reglas.append(ReglaFallida(nombre, False, res.error_code, msg))

    # R1 — Campos obligatorios
    _anotar("R1", validar_campos_obligatorios(datos))

    # R2 — Fecha (solo si está presente)
    fecha = datos.get("fecha")
    if fecha is not None:
        _anotar("R2", validar_fecha(str(fecha)))

    # R3 — Moneda
    moneda = datos.get("moneda")
    if moneda is not None:
        _anotar("R3", validar_moneda(str(moneda)))

    # R4 — Coherencia aritmética
    subtotal = datos.get("subtotal")
    iva = datos.get("iva")
    total = datos.get("total")
    if subtotal is not None and iva is not None and total is not None:
        _anotar("R4", validar_aritmetica(float(subtotal), float(iva), float(total)))

    # R6 — Categoría
    categoria = datos.get("categoria")
    if categoria is not None:
        _anotar("R6", validar_categoria(str(categoria), CLOSED_CATEGORY_LIST))

    return ResultadoFactura(reglas=reglas)
