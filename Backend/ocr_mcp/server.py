# -*- coding: utf-8 -*-
"""
ocr_mcp/server.py — Servidor MCP stdio para OCR de facturas.

Herramienta expuesta: ``ocr_imagen(ruta: str)``.

Validaciones previas a invocar el LLM de visión:
  - ``ruta`` normalizada/resuelta debe estar dentro de INVOICES_DIR (R1.2, R1.4)
  - extensión en {.jpg, .jpeg, .png, .pdf} y tamaño <= 10 MB (R1.3)

El resultado siempre se marca como contenido no confiable (R1.5).
Los errores se devuelven como ``isError: true``; el servidor nunca termina.
Todo diagnóstico va a ``sys.stderr``; nunca se escribe a stdout salvo el protocolo.
"""

from __future__ import annotations

import os
import sys
import traceback

# UTF-8 forzado en stdin/stdout (protocolo stdio JSON-RPC).
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from finanzas_mcp.models import OcrResult
from ocr_mcp.ocr_client import OcrClient
from ocr_mcp.ocr_core import (  # noqa: F401
    ALLOWED_EXTENSIONS,
    OcrToolError,
    validar_ruta,
    wrap_untrusted,
)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

INVOICES_DIR: str = os.environ.get("INVOICES_DIR", "./facturas")
MAX_FILE_SIZE_BYTES: int = int(os.environ.get("MAX_IMAGE_BYTES", 10 * 1024 * 1024))


# ---------------------------------------------------------------------------
# Servidor MCP
# ---------------------------------------------------------------------------

server = Server("ocr-mcp")
_client: OcrClient | None = None


def _get_client() -> OcrClient:
    global _client
    if _client is None:
        _client = OcrClient(
            model=os.environ.get("OCR_MODEL") or None,
        )
    return _client


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="ocr_imagen",
            description=(
                "Extrae texto de una imagen de factura usando un LLM con visión. "
                "Devuelve contenido no confiable."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ruta": {
                        "type": "string",
                        "description": "Ruta absoluta dentro de la carpeta de facturas",
                    }
                },
                "required": ["ruta"],
            },
        )
    ]


async def _ocr_imagen(arguments: dict) -> list[types.TextContent]:
    ruta = arguments.get("ruta")
    resolved = validar_ruta(ruta)  # type: ignore[arg-type]
    try:
        result = await anyio.to_thread.run_sync(_get_client().extract, str(resolved))
    except Exception as exc:
        print(
            f"[ocr-mcp] Fallo del cliente OCR: {traceback.format_exc()}",
            file=sys.stderr,
        )
        raise OcrToolError("OCR_FAILURE", f"Error al procesar la imagen: {type(exc).__name__}") from exc
    return [types.TextContent(type="text", text=wrap_untrusted(result))]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Despacha ocr_imagen. Cualquier excepción la convierte el framework en
    ``isError: true`` sin terminar el servidor."""
    print(f"[ocr-mcp] Llamada a herramienta: '{name}'", file=sys.stderr)
    try:
        if name != "ocr_imagen":
            raise ValueError(f"Herramienta desconocida: '{name}'")
        return await _ocr_imagen(arguments or {})
    except OcrToolError as exc:
        print(f"[ocr-mcp] Error de negocio {exc}", file=sys.stderr)
        raise
    except Exception:
        print(f"[ocr-mcp] Error inesperado: {traceback.format_exc()}", file=sys.stderr)
        raise


async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def main() -> None:
    """Punto de entrada: stdio (defecto) o Streamable HTTP (``--transport streamable-http``)."""
    from mcp_transport import ejecutar

    ejecutar(server, lambda: anyio.run(_main), puerto_defecto=8002)


if __name__ == "__main__":
    main()
