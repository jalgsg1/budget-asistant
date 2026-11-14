# -*- coding: utf-8 -*-
"""
Lógica de negocio para registro y consulta de transacciones.

Este módulo ejecuta la revalidación completa R1–R8 de forma independiente al
agente antes de persistir cualquier transacción, e impone la lista blanca de
filtros y el rango máximo de fechas para las consultas.

No importa `mcp`, `sys.stdin` ni `sys.stdout`.

Requirements: 2.3, 3.4, 4.3, 5.4, 6.4, 6.5, 7.4, 8.3, 8.4, 9.2, 9.3,
              10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

import math
import sys
from datetime import date, datetime
from typing import Any

from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import Transaction, ValidationResult
from finanzas_mcp.business.hitl import (
    CODIGO_AUTO_NO_PERMITIDO,
    CODIGO_MONTO_ALTO,
    PoliticaHitlError,
    decidir_rechazo_automatico,
    es_token_automatico,
    resolver_parametros_hitl,
)
from finanzas_mcp.business.validacion import (
    validar_campos_obligatorios,
    validar_fecha,
    validar_moneda,
    validar_aritmetica,
    validar_categoria,
    validar_monto_alto,
    validar_token_confirmacion,
)


# ---------------------------------------------------------------------------
# Excepciones de negocio
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Se lanza cuando alguna validación R1–R8 falla durante el registro.

    Attributes
    ----------
    result:
        El ``ValidationResult`` con ``is_valid=False`` que originó el error.
    """

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        super().__init__(
            f"[{result.error_code}] {'; '.join(result.errors)}"
        )


class FilterError(Exception):
    """Se lanza cuando ``listar_transacciones`` recibe un filtro no permitido.

    Attributes
    ----------
    error_code:
        ``"INVALID_FILTER"`` siempre.
    invalid_keys:
        Claves que no pertenecen a la lista blanca.
    """

    error_code: str = "INVALID_FILTER"

    def __init__(self, invalid_keys: list[str]) -> None:
        self.invalid_keys = invalid_keys
        super().__init__(
            f"[INVALID_FILTER] Filtros no permitidos: {', '.join(invalid_keys)}"
        )


class DateRangeError(Exception):
    """Se lanza cuando el rango de fechas supera ``max_rango_dias``.

    Attributes
    ----------
    error_code:
        ``"DATE_RANGE_EXCEEDED"`` siempre.
    """

    error_code: str = "DATE_RANGE_EXCEEDED"

    def __init__(self, desde: str, hasta: str, max_dias: int, actual: int) -> None:
        self.desde = desde
        self.hasta = hasta
        self.max_dias = max_dias
        self.actual = actual
        super().__init__(
            f"[DATE_RANGE_EXCEEDED] El rango de fechas entre '{desde}' y '{hasta}' "
            f"es de {actual} día(s), superando el máximo permitido de {max_dias} día(s)."
        )


# ---------------------------------------------------------------------------
# Registro de transacción (R1–R8 — defensa en profundidad)
# ---------------------------------------------------------------------------

def registrar_transaccion(
    repo: TransactionRepository,
    datos: dict[str, Any],
    token: str | None,
    high_amount_token: str | None,
    policy: dict[str, Any],
    user_id: str,
    confianza_ocr: float | None = None,
    contenido_sospechoso: bool | None = None,
) -> int:
    """Revalida R1–R8 de forma independiente y persiste la transacción si todo pasa.

    Si ``token`` es un Token_Automatico (``auto:...``) solo se acepta en modo
    ``adaptativo`` (según la política del servidor) y tras revalidar que la
    factura es limpia; ``confianza_ocr`` y ``contenido_sospechoso`` solo se
    usan en esa rama y su ausencia implica rechazo (falla cerrada).

    El ``user_id`` **siempre** se inyecta desde el contexto de sesión de
    confianza; nunca se toma del payload ``datos`` suministrado por el agente.
    Esto protege contra escalado de privilegios (Requirements 10.1, 10.3).

    Parameters
    ----------
    repo:
        Repositorio de transacciones.
    datos:
        Diccionario de campos extraídos de la factura (payload del agente).
        El campo ``user_id`` en ``datos``, si existe, es ignorado.
    token:
        Token de confirmación estándar (R8).
    high_amount_token:
        Token de confirmación para montos altos (R7).  Puede ser ``None`` si el
        total no supera el umbral.
    policy:
        Diccionario cargado de ``politica.json`` con al menos las claves
        ``high_amount_threshold`` y ``allowed_filters``.
    user_id:
        Identificador del usuario propietario de la transacción.
        **Debe provenir del contexto de sesión, nunca de ``datos``.**

    Returns
    -------
    int
        El ``id`` de la transacción recién insertada.

    Raises
    ------
    ValidationError
        Si cualquier validación R1–R8 falla.
    """
    # Política HITL solo del servidor (nunca del payload); falla cerrada.
    es_auto = es_token_automatico(token)
    try:
        params = resolver_parametros_hitl(policy, exigir_umbral=False)
        modo_hitl, umbral_ocr = params.modo_hitl, params.umbral_confianza_ocr
    except PoliticaHitlError as exc:
        print(f"[finanzas-mcp] Política HITL inválida, se usa 'siempre': {exc}", file=sys.stderr)
        modo_hitl, umbral_ocr = "siempre", 1.0

    if es_auto and modo_hitl != "adaptativo":
        raise ValidationError(
            ValidationResult(
                is_valid=False,
                errors=["Un token automático no está permitido en este modo."],
                error_code=CODIGO_AUTO_NO_PERMITIDO,
            )
        )

    # ------------------------------------------------------------------
    # R1 — Campos obligatorios
    # ------------------------------------------------------------------
    result_r1 = validar_campos_obligatorios(datos)
    if not result_r1.is_valid:
        raise ValidationError(result_r1)

    # ------------------------------------------------------------------
    # R2 — Validez de fecha
    # ------------------------------------------------------------------
    result_r2 = validar_fecha(datos["fecha"])
    if not result_r2.is_valid:
        raise ValidationError(result_r2)

    # ------------------------------------------------------------------
    # R3 — Lista blanca de moneda
    # ------------------------------------------------------------------
    result_r3 = validar_moneda(datos["moneda"])
    if not result_r3.is_valid:
        raise ValidationError(result_r3)

    # ------------------------------------------------------------------
    # R4 — Coherencia aritmética (solo cuando subtotal e iva están presentes)
    # En la rama automática se evalúa dentro de decidir_rechazo_automatico.
    # ------------------------------------------------------------------
    subtotal = datos.get("subtotal")
    iva = datos.get("iva")
    aritmetica_invalida = False
    if subtotal is not None and iva is not None:
        result_r4 = validar_aritmetica(
            float(subtotal), float(iva), float(datos["total"])
        )
        if not result_r4.is_valid:
            if not es_auto:
                raise ValidationError(result_r4)
            aritmetica_invalida = True

    # ------------------------------------------------------------------
    # R6 — Lista blanca de categoría
    # ------------------------------------------------------------------
    result_r6 = validar_categoria(datos["categoria"])
    if not result_r6.is_valid:
        raise ValidationError(result_r6)

    # ------------------------------------------------------------------
    # R7 — Token para monto alto
    # ------------------------------------------------------------------
    high_amount_threshold = policy.get("high_amount_threshold", {})
    moneda = datos["moneda"].strip().upper()
    # Resolve per-currency threshold; fall back to a simple scalar if the
    # policy stores a single number instead of a per-currency dict.
    if isinstance(high_amount_threshold, dict):
        umbral = high_amount_threshold.get(moneda, high_amount_threshold.get("USD", 0))
    else:
        umbral = float(high_amount_threshold)

    if es_auto:
        # Token automático: nunca sustituye la confirmación humana de monto
        # alto ni de ninguna otra alerta; high_amount_token se ignora.
        monto_alto = float(datos["total"]) > float(umbral)
        try:
            duplicado = bool(
                repo.find_duplicates(
                    comercio=datos["comercio"],
                    fecha=datos["fecha"],
                    total=float(datos["total"]),
                    user_id=user_id,
                    limit=1,
                )
            )
        except Exception:
            duplicado = True  # falla cerrada
        confianza_ok = (
            isinstance(confianza_ocr, (int, float))
            and not isinstance(confianza_ocr, bool)
            and math.isfinite(confianza_ocr)
            and confianza_ocr >= umbral_ocr
        )
        codigo = decidir_rechazo_automatico(
            monto_alto=monto_alto,
            aritmetica_invalida=aritmetica_invalida,
            duplicado=duplicado,
            confianza_baja_o_ausente=not confianza_ok,
            contenido_sospechoso_o_ausente=contenido_sospechoso is not False,
        )
        if codigo is not None:
            mensaje = (
                "Se requiere confirmación humana de monto alto."
                if codigo == CODIGO_MONTO_ALTO
                else "Se requiere confirmación humana."
            )
            raise ValidationError(
                ValidationResult(is_valid=False, errors=[mensaje], error_code=codigo)
            )
        return repo.insert(
            Transaction(
                user_id=user_id,
                comercio=datos["comercio"],
                fecha=datos["fecha"],
                total=float(datos["total"]),
                moneda=moneda,
                categoria=datos["categoria"].strip(),
                subtotal=float(subtotal) if subtotal is not None else None,
                iva=float(iva) if iva is not None else None,
                descripcion=datos.get("descripcion"),
            )
        )

    result_r7 = validar_monto_alto(
        total=float(datos["total"]),
        umbral=float(umbral),
        token=high_amount_token,
    )
    if not result_r7.is_valid:
        raise ValidationError(result_r7)

    # ------------------------------------------------------------------
    # R8 — Token de confirmación estándar
    # ------------------------------------------------------------------
    result_r8 = validar_token_confirmacion(token)
    if not result_r8.is_valid:
        raise ValidationError(result_r8)

    # ------------------------------------------------------------------
    # Persistencia — solo si todo pasa (Requirements 8.3, 8.4)
    # user_id del contexto de sesión, no de ``datos`` (Req. 10.1, 10.3)
    # ------------------------------------------------------------------
    tx = Transaction(
        user_id=user_id,                              # siempre del contexto
        comercio=datos["comercio"],
        fecha=datos["fecha"],
        total=float(datos["total"]),
        moneda=moneda,
        categoria=datos["categoria"].strip(),
        subtotal=float(subtotal) if subtotal is not None else None,
        iva=float(iva) if iva is not None else None,
        descripcion=datos.get("descripcion"),
    )
    return repo.insert(tx)


# ---------------------------------------------------------------------------
# Listado de transacciones (R9 — lista blanca de filtros)
# ---------------------------------------------------------------------------

def listar_transacciones(
    repo: TransactionRepository,
    filtros: dict[str, Any],
    user_id: str,
    filtros_permitidos: list[str],
    max_rango_dias: int,
) -> list[Transaction]:
    """Lista transacciones del usuario aplicando lista blanca de filtros y rango de fechas.

    Parameters
    ----------
    repo:
        Repositorio de transacciones.
    filtros:
        Diccionario de filtros solicitados por el agente.
    user_id:
        Identificador del usuario propietario.  Siempre del contexto de sesión
        (Requirement 10.3).
    filtros_permitidos:
        Lista blanca de claves de filtro aceptadas (R9 — Requirement 10.1, 10.4).
        Cualquier clave fuera de esta lista produce un ``FilterError``.
    max_rango_dias:
        Número máximo de días entre ``fecha_desde`` y ``fecha_hasta``
        (Requirement 10.2).

    Returns
    -------
    list[Transaction]
        Transacciones que cumplen los filtros, ordenadas por fecha descendente.

    Raises
    ------
    FilterError
        Si cualquier clave de ``filtros`` no está en ``filtros_permitidos``.
    DateRangeError
        Si el rango entre ``fecha_desde`` y ``fecha_hasta`` supera ``max_rango_dias``.
    """
    # ------------------------------------------------------------------
    # R9 — Lista blanca de filtros (Requirements 10.1, 10.4)
    # ------------------------------------------------------------------
    invalid_keys = [k for k in filtros if k not in filtros_permitidos]
    if invalid_keys:
        raise FilterError(invalid_keys)

    # ------------------------------------------------------------------
    # Rango máximo de fechas (Requirement 10.2)
    # ------------------------------------------------------------------
    fecha_desde_str: str | None = filtros.get("fecha_desde")
    fecha_hasta_str: str | None = filtros.get("fecha_hasta")

    if fecha_desde_str is not None and fecha_hasta_str is not None:
        try:
            fecha_desde = datetime.strptime(fecha_desde_str.strip(), "%Y-%m-%d").date()
            fecha_hasta = datetime.strptime(fecha_hasta_str.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(
                ValidationResult(
                    is_valid=False,
                    errors=[f"Formato de fecha inválido en los filtros: {exc}"],
                    error_code="INVALID_DATE_FORMAT",
                )
            ) from exc

        delta_dias = (fecha_hasta - fecha_desde).days
        if delta_dias > max_rango_dias:
            raise DateRangeError(
                desde=fecha_desde_str,
                hasta=fecha_hasta_str,
                max_dias=max_rango_dias,
                actual=delta_dias,
            )

    # ------------------------------------------------------------------
    # Aislamiento por user_id — siempre del contexto de sesión (Req. 10.3)
    # ------------------------------------------------------------------
    return repo.query(filters=filtros, user_id=user_id)
