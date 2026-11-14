# -*- coding: utf-8 -*-
"""
mcp_transport.py — Selección de transporte para los servidores MCP.

* ``stdio`` (por defecto): el comportamiento original, un proceso hijo por cliente.
* ``streamable-http``: servidor HTTP (Starlette + uvicorn) con el endpoint MCP en
  ``/mcp`` y un ``/health`` para healthchecks de Docker Compose.

Configuración (argumento CLI > variable de entorno > valor por defecto)::

    --transport / MCP_TRANSPORT   stdio | streamable-http   (stdio)
    --host      / MCP_HOST        0.0.0.0                   (solo HTTP)
    --port      / MCP_PORT        puerto por servidor       (solo HTTP)

En modo HTTP el ``user_id`` sigue saliendo de ``MCP_USER_ID`` del proceso servidor,
nunca del payload del cliente.
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from typing import Callable, Optional, Sequence

TRANSPORTS = ("stdio", "streamable-http")
MCP_PATH = "/mcp"


def crear_app_http(server):
    """Construye la app ASGI que sirve ``server`` por Streamable HTTP en ``/mcp``."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    manager = StreamableHTTPSessionManager(app=server)

    class _McpAsgi:
        # Clase (no función) para que Starlette la trate como app ASGI cruda.
        async def __call__(self, scope, receive, send) -> None:
            await manager.handle_request(scope, receive, send)

    async def health(_request):
        return JSONResponse({"status": "ok"})

    @asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return Starlette(
        routes=[
            Route(MCP_PATH, endpoint=_McpAsgi(), methods=["GET", "POST", "DELETE"]),
            Route("/health", health),
        ],
        lifespan=lifespan,
    )


def ejecutar(
    server,
    main_stdio: Callable[[], None],
    puerto_defecto: int,
    argv: Optional[Sequence[str]] = None,
) -> None:
    """Arranca ``server`` con el transporte elegido."""
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--transport", choices=TRANSPORTS,
        default=os.environ.get("MCP_TRANSPORT", "stdio").strip().lower(),
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MCP_PORT") or puerto_defecto)
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.transport == "stdio":
        main_stdio()
        return

    import uvicorn

    print(
        f"[mcp] Streamable HTTP en http://{args.host}:{args.port}{MCP_PATH}",
        file=sys.stderr,
    )
    uvicorn.run(crear_app_http(server), host=args.host, port=args.port, log_level="info")
