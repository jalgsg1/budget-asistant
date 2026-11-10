# -*- coding: utf-8 -*-
"""
Lógica de negocio para detección de transacciones duplicadas.

Este módulo no importa `mcp`, `sys.stdin` ni `sys.stdout`, de modo que puede
usarse tanto desde el adaptador MCP como desde cualquier capa HTTP futura.

Requirements: 6.1, 6.2, 6.3, 6.4, 10.3
"""

from __future__ import annotations

from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import Transaction


def buscar_duplicados(
    repo: TransactionRepository,
    comercio: str,
    fecha: str,
    total: float,
    user_id: str,
    limit: int = 10,
) -> list[Transaction]:
    """Buscar transacciones que coincidan con comercio, fecha y total para un usuario.

    El ``user_id`` proviene **siempre** del contexto de sesión de confianza y
    nunca del payload suministrado por el agente.  Esto es una defensa explícita
    contra escalado de privilegios (Requirement 10.3).

    Parameters
    ----------
    repo:
        Repositorio de transacciones al que delegar la consulta.
    comercio:
        Nombre exacto del comercio (sensible a mayúsculas/minúsculas).
    fecha:
        Fecha de la transacción en formato ISO 8601 (YYYY-MM-DD).
    total:
        Monto total de la transacción.
    user_id:
        Identificador del usuario propietario de las transacciones.
        **Debe provenir del contexto de sesión, nunca del payload del agente.**
    limit:
        Número máximo de resultados a devolver.  El repositorio aplica además un
        tope absoluto de 10 (Property 7 — Requirement 6.2).

    Returns
    -------
    list[Transaction]
        Lista de transacciones duplicadas candidatas, con como máximo ``limit``
        elementos (nunca más de 10 en ningún caso).
    """
    # Clamp defensivo: aunque el repositorio ya aplica min(limit, 10), esta capa
    # lo reafirma para que la intención de diseño quede explícita aquí también
    # (Requirement 6.2 — resultado acotado a 10).
    effective_limit = min(limit, 10)

    return repo.find_duplicates(
        comercio=comercio,
        fecha=fecha,
        total=total,
        user_id=user_id,          # siempre del contexto de sesión (Req. 10.3)
        limit=effective_limit,
    )
