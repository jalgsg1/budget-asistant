# -*- coding: utf-8 -*-
"""
api_pruebas/mcp_remoto.py — Herramientas del Pipeline sobre MCP Streamable HTTP.

Si ``FINANZAS_MCP_URL`` / ``OCR_MCP_URL`` están definidas (docker compose), el
Pipeline de ``/pipeline`` y ``/batch`` llama a los servidores MCP reales por HTTP.
Si no, se usan los servicios en proceso (``construir_tools``), sin ``mcp``.

``agent.main`` importa ``mcp`` de forma diferida, así que este módulo es seguro de
importar aunque no se use MCP.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from api_pruebas.config import Config
from api_pruebas.errores import ErrorApi
from api_pruebas.herramientas import construir_tools
from api_pruebas.servicios import ServiciosNegocio


@contextmanager
def herramientas_pipeline(
    servicios: ServiciosNegocio, config: Config
) -> Iterator[dict[str, Callable[[dict], Any]]]:
    from agent.main import McpToolbox, mcp_http_configurado

    if not mcp_http_configurado():
        yield construir_tools(servicios)
        return

    try:
        caja = McpToolbox(config.user_id)
        caja.__enter__()
    except Exception as exc:  # noqa: BLE001 - solo se expone el tipo
        raise ErrorApi(
            502,
            "MCP_UNAVAILABLE",
            f"No se pudo conectar con los servidores MCP ({type(exc).__name__}).",
        ) from None
    try:
        yield caja.tools
    finally:
        caja.close()
