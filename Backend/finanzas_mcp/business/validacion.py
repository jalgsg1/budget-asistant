# -*- coding: utf-8 -*-
"""
Funciones de validación de negocio para gestor-facturas.

Cada función retorna un ``ValidationResult`` y no tiene dependencia de
``mcp``, ``sys.stdin`` ni ``sys.stdout``, de modo que puede ser invocada
tanto desde el servidor MCP como desde un handler HTTP futuro.

Reglas implementadas
--------------------
R1  validar_campos_obligatorios  — comercio, fecha, total, moneda, categoría
R2  validar_fecha                — formato ISO 8601 y no en el futuro
R3  validar_moneda               — solo CRC o USD
R4  validar_aritmetica           — |subtotal + iva - total| <= 0.01
R6  validar_categoria            — valor en CLOSED_CATEGORY_LIST
R7  validar_monto_alto           — token requerido cuando total > umbral
R8  validar_token_confirmacion   — token no nulo y no vacío
"""

from __future__ import annotations

from datetime import date, datetime

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.constantes import CAMPOS_OBLIGATORIOS, MONEDAS_VALIDAS
from finanzas_mcp.models import ValidationResult

# ---------------------------------------------------------------------------
# Constantes internas (alias de finanzas_mcp.constantes)
# ---------------------------------------------------------------------------

_MONEDAS_VALIDAS: frozenset[str] = MONEDAS_VALIDAS
_CAMPOS_OBLIGATORIOS: tuple[str, ...] = CAMPOS_OBLIGATORIOS


# ---------------------------------------------------------------------------
# R1 — Campos obligatorios
# ---------------------------------------------------------------------------

def validar_campos_obligatorios(datos: dict) -> ValidationResult:
    """R1: verifica presencia y no-vacío de comercio, fecha, total, moneda y categoría.

    Parameters
    ----------
    datos:
        Diccionario de campos extraídos de la factura.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si todos los campos están presentes y no vacíos;
        ``is_valid=False`` con ``error_code="MISSING_FIELDS"`` en caso contrario.
    """
    missing: list[str] = []

    for campo in _CAMPOS_OBLIGATORIOS:
        valor = datos.get(campo)
        if valor is None:
            missing.append(campo)
        elif isinstance(valor, str) and not valor.strip():
            missing.append(campo)
        # total can be 0.0 which is falsy but valid; only None / empty string count as missing

    if missing:
        return ValidationResult(
            is_valid=False,
            errors=[f"Campos obligatorios ausentes o vacíos: {', '.join(missing)}"],
            error_code="MISSING_FIELDS",
        )

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# R2 — Fecha
# ---------------------------------------------------------------------------

def validar_fecha(fecha: str) -> ValidationResult:
    """R2: verifica formato ISO 8601 (YYYY-MM-DD) y que la fecha no sea futura.

    Parameters
    ----------
    fecha:
        Cadena de fecha candidata.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si el formato es correcto y la fecha no es futura.
        ``error_code`` será ``"INVALID_DATE_FORMAT"`` o ``"FUTURE_DATE"`` según el caso.
    """
    if not fecha or not isinstance(fecha, str):
        return ValidationResult(
            is_valid=False,
            errors=["El campo 'fecha' está vacío o no es una cadena de texto."],
            error_code="INVALID_DATE_FORMAT",
        )

    try:
        parsed: date = datetime.strptime(fecha.strip(), "%Y-%m-%d").date()
    except ValueError:
        return ValidationResult(
            is_valid=False,
            errors=[
                f"El formato de fecha '{fecha}' no es válido. "
                "Se esperaba el formato ISO 8601: YYYY-MM-DD."
            ],
            error_code="INVALID_DATE_FORMAT",
        )

    today: date = date.today()
    if parsed > today:
        return ValidationResult(
            is_valid=False,
            errors=[
                f"La fecha '{fecha}' es posterior a la fecha actual ({today.isoformat()}). "
                "No se permiten fechas futuras."
            ],
            error_code="FUTURE_DATE",
        )

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# R3 — Moneda
# ---------------------------------------------------------------------------

def validar_moneda(moneda: str) -> ValidationResult:
    """R3: verifica que moneda sea CRC o USD.

    Parameters
    ----------
    moneda:
        Código de moneda candidato.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si la moneda es ``"CRC"`` o ``"USD"``.
        ``error_code="INVALID_CURRENCY"`` en caso contrario.
    """
    if not moneda or not isinstance(moneda, str):
        return ValidationResult(
            is_valid=False,
            errors=["El campo 'moneda' está vacío o no es una cadena de texto."],
            error_code="INVALID_CURRENCY",
        )

    if moneda.strip().upper() not in _MONEDAS_VALIDAS:
        return ValidationResult(
            is_valid=False,
            errors=[
                f"Moneda '{moneda}' no soportada. "
                f"Monedas aceptadas: {', '.join(sorted(_MONEDAS_VALIDAS))}."
            ],
            error_code="INVALID_CURRENCY",
        )

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# R4 — Coherencia aritmética
# ---------------------------------------------------------------------------

def validar_aritmetica(subtotal: float, iva: float, total: float) -> ValidationResult:
    """R4: verifica que |subtotal + iva - total| <= 0.01 cuando ambos están presentes.

    Parameters
    ----------
    subtotal:
        Monto antes de impuestos.
    iva:
        Monto del impuesto.
    total:
        Monto final pagado.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si la diferencia está dentro de la tolerancia de ±0.01.
        ``error_code="ARITHMETIC_INCONSISTENCY"`` en caso contrario.
    """
    # Redondear a 2 decimales evita falsos rechazos por error de punto flotante
    # (p. ej. 100.0 + 13.0 - 113.01 = 0.01000000000000512).
    diferencia: float = round(abs(subtotal + iva - total), 2)

    if diferencia > 0.01:
        return ValidationResult(
            is_valid=False,
            errors=[
                f"Inconsistencia aritmética: subtotal ({subtotal}) + IVA ({iva}) = "
                f"{subtotal + iva:.4f}, pero el total es {total}. "
                f"Diferencia: {diferencia:.4f} (máximo permitido: 0.01)."
            ],
            error_code="ARITHMETIC_INCONSISTENCY",
        )

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# R6 — Categoría
# ---------------------------------------------------------------------------

def validar_categoria(
    categoria: str,
    lista: list[str] | None = None,
) -> ValidationResult:
    """R6: verifica que categoría esté en la lista cerrada de categorías.

    Parameters
    ----------
    categoria:
        Categoría candidata extraída de la factura.
    lista:
        Lista de categorías aceptadas.  Si se omite se usa ``CLOSED_CATEGORY_LIST``.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si la categoría está en la lista.
        ``error_code="INVALID_CATEGORY"`` en caso contrario.
    """
    categorias_validas: list[str] = lista if lista is not None else CLOSED_CATEGORY_LIST

    if not categoria or not isinstance(categoria, str):
        return ValidationResult(
            is_valid=False,
            errors=["El campo 'categoría' está vacío o no es una cadena de texto."],
            error_code="INVALID_CATEGORY",
        )

    if categoria.strip() not in categorias_validas:
        return ValidationResult(
            is_valid=False,
            errors=[
                f"Categoría '{categoria}' no reconocida. "
                f"Categorías aceptadas: {', '.join(categorias_validas)}."
            ],
            error_code="INVALID_CATEGORY",
        )

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# R7 — Monto alto
# ---------------------------------------------------------------------------

def validar_monto_alto(
    total: float,
    umbral: float,
    token: str | None,
) -> ValidationResult:
    """R7: si total > umbral, verifica que el token de confirmación esté presente.

    Parameters
    ----------
    total:
        Monto total de la transacción.
    umbral:
        Límite monetario a partir del cual se exige confirmación adicional.
    token:
        Token de confirmación para montos altos provisto por el usuario.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si el total no supera el umbral, o si lo supera y el
        token está presente y no vacío.
        ``error_code="HIGH_AMOUNT_CONFIRMATION_REQUIRED"`` cuando el token falta.
    """
    if total > umbral:
        if not token or not isinstance(token, str) or not token.strip():
            return ValidationResult(
                is_valid=False,
                errors=[
                    f"El monto {total} supera el umbral de {umbral}. "
                    "Se requiere un token de confirmación adicional para montos altos."
                ],
                error_code="HIGH_AMOUNT_CONFIRMATION_REQUIRED",
            )

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# R8 — Token de confirmación
# ---------------------------------------------------------------------------

def validar_token_confirmacion(token: str | None) -> ValidationResult:
    """R8: verifica que el token de confirmación no sea nulo ni vacío.

    Parameters
    ----------
    token:
        Token de confirmación proporcionado por el usuario antes de registrar.

    Returns
    -------
    ValidationResult
        ``is_valid=True`` si el token está presente y no es una cadena vacía.
        ``error_code="MISSING_CONFIRMATION_TOKEN"`` en caso contrario.
    """
    if not token or not isinstance(token, str) or not token.strip():
        return ValidationResult(
            is_valid=False,
            errors=[
                "Se requiere un token de confirmación válido para registrar la transacción."
            ],
            error_code="MISSING_CONFIRMATION_TOKEN",
        )

    return ValidationResult(is_valid=True)
