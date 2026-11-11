# -*- coding: utf-8 -*-
"""
api_pruebas/herramientas.py — Adaptador de herramientas del Pipeline sin MCP.

``construir_tools`` devuelve ``{nombre: callable(dict) -> resultado}`` con las mismas
cinco claves de ``agent.main.TOOL_SERVERS`` y el mismo contrato que ``McpToolbox.tools``.
Las operaciones usan ``ServiciosNegocio`` (``user_id`` siempre de la configuración).
Nunca importa ``mcp``.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.agent import ToolError
from api_pruebas.errores import mapear_excepcion
from api_pruebas.servicios import ServiciosNegocio

# Claves esperadas (mismas que agent.main.TOOL_SERVERS, sin importar ese módulo).
NOMBRES_TOOLS = (
    "ocr_imagen",
    "validar_factura",
    "buscar_duplicados",
    "listar_transacciones",
    "registrar_transaccion",
)


def _tx_a_dict(tx: Any) -> dict:
    return {
        "id": tx.id,
        "user_id": tx.user_id,
        "comercio": tx.comercio,
        "fecha": tx.fecha,
        "total": tx.total,
        "moneda": tx.moneda,
        "categoria": tx.categoria,
        "subtotal": tx.subtotal,
        "iva": tx.iva,
        "descripcion": tx.descripcion,
        "created_at": tx.created_at,
    }


def _como_toolerror(func: Callable[[dict], Any]) -> Callable[[dict], Any]:
    """Convierte excepciones de negocio en ``ToolError`` con el mismo código."""

    def envoltura(args: dict) -> Any:
        try:
            return func(args)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            _, code, msg = mapear_excepcion(exc)
            raise ToolError(code, msg) from None

    return envoltura


def construir_tools(servicios: ServiciosNegocio) -> dict[str, Callable[[dict], Any]]:
    """Crea las herramientas del Pipeline respaldadas por ``servicios``."""

    def ocr_imagen(args: dict) -> str:
        respuesta = servicios.ocr_ruta(str(args.get("ruta", args.get("image_path", ""))))
        envuelto = respuesta.model_dump()
        envuelto.pop("ruta", None)
        return json.dumps(envuelto, ensure_ascii=False)

    def validar_factura(args: dict) -> dict:
        res = servicios.validar(args)
        if not res.valid:
            codigo = res.first_error_code or "VALIDATION_ERROR"
            raise ToolError(codigo, "; ".join(res.errors))
        return {"is_valid": True, "errors": []}

    def buscar_duplicados(args: dict) -> list[dict]:
        duplicados = servicios.duplicados(
            str(args.get("comercio", "")),
            str(args.get("fecha", "")),
            float(args.get("total", 0.0)),
        )
        return [_tx_a_dict(tx) for tx in duplicados]

    def listar_transacciones(args: dict) -> list[dict]:
        filas = servicios.listar(dict(args.get("filtros") or {}))
        return [_tx_a_dict(tx) for tx in filas]

    def registrar_transaccion(args: dict) -> dict:
        # servicios.registrar descarta user_id y tokens del payload de datos.
        tx_id = servicios.registrar(
            dict(args),
            args.get("confirmation_token"),
            args.get("high_amount_token"),
        )
        return {"id": tx_id, "status": "registrada"}

    return {
        "ocr_imagen": _como_toolerror(ocr_imagen),
        "validar_factura": _como_toolerror(validar_factura),
        "buscar_duplicados": _como_toolerror(buscar_duplicados),
        "listar_transacciones": _como_toolerror(listar_transacciones),
        "registrar_transaccion": _como_toolerror(registrar_transaccion),
    }
