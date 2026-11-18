# -*- coding: utf-8 -*-
"""
finanzas_mcp/server.py — Adaptador MCP stdio para gestor-facturas.

Este módulo es el único punto del paquete que tiene dependencia de `mcp`,
`sys.stdin` y `sys.stdout`.  Toda la lógica de negocio vive en
`finanzas_mcp/business/`, de modo que pueda invocarse sin MCP desde un
handler HTTP en el futuro.

Herramientas expuestas (Requisito 17.1):
  - validar_factura
  - buscar_duplicados
  - listar_transacciones
  - registrar_transaccion

Protocolo (Requisito 17.2):
  stdio, JSON-RPC 2.0, un mensaje por línea, UTF-8 forzado en stdin y stdout.

Manejo de errores (Requisito 17.4):
  Las violaciones de reglas de negocio devuelven {"isError": true, "content": [...]}.
  El servidor nunca termina por un error de negocio.

Diagnósticos (Requisito 17.5):
  Todo mensaje de diagnóstico va a sys.stderr; nunca se hace print() a stdout.

user_id:
  El ``user_id`` para todas las operaciones se inyecta desde el contexto de
  sesión MCP.  La librería `mcp` 1.9.x no expone directamente un campo de
  identidad en el ``request_context``; como medida provisional se lee la
  variable de entorno ``MCP_USER_ID`` con un valor de respaldo ``"default_user"``.
  Cuando el sistema evolucione hacia autenticación real, esta función debe
  reemplazarse por la lectura del token de sesión apropiado.
  NOTA: el ``user_id`` del payload del agente se ignora deliberadamente para
  prevenir escalado de privilegios (Requisito 10.3).
"""

from __future__ import annotations

import json
import os
import sys
import traceback

# Forzar UTF-8 en stdin/stdout antes de importar cualquier cosa que use IO
# (Requisito 17.2 y requisito técnico del curso).
# La librería mcp.server.stdio ya re-envuelve con UTF-8, pero hacemos el
# reconfigure aquí también para cualquier código que pueda acceder a
# sys.stdout directamente durante la inicialización.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.business.duplicados import buscar_duplicados as _buscar_duplicados
from finanzas_mcp.business.transacciones import (
    DateRangeError,
    FilterError,
    ValidationError,
    listar_transacciones as _listar_transacciones,
    registrar_transaccion as _registrar_transaccion,
)
from finanzas_mcp.business.validacion import (
    validar_aritmetica,
    validar_campos_obligatorios,
    validar_categoria,
    validar_fecha,
    validar_moneda,
)
from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.business.factura import evaluar_factura
from finanzas_mcp.models import Transaction, ValidationResult

# ---------------------------------------------------------------------------
# Configuración de runtime
# ---------------------------------------------------------------------------

#: Ruta a la base de datos SQLite. Lee DB_PATH del entorno; por defecto ./data/facturas.db.
_DB_PATH: str = os.environ.get("DB_PATH", "./data/facturas.db")

#: Ruta al archivo de política. Se busca junto al directorio del proyecto.
_POLICY_PATH: str = os.environ.get(
    "POLICY_PATH",
    os.path.join(os.path.dirname(__file__), "..", "politica.json"),
)


def _load_policy(path: str) -> dict:
    """Carga politica.json al arrancar el servidor."""
    resolved = os.path.normpath(os.path.abspath(path))
    try:
        with open(resolved, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print(
            f"[finanzas-mcp] ADVERTENCIA: politica.json no encontrado en '{resolved}'. "
            "Se usará política por defecto.",
            file=sys.stderr,
        )
        return {
            "tools": {},
            "step_limit": 8,
            "token_limit": 4000,
            "high_amount_threshold": {"CRC": 50000, "USD": 100},
            "max_date_range_days": 90,
            "modo_hitl": "siempre",
            "umbral_confianza_ocr": 0.75,
            "allowed_filters": [
                "comercio",
                "fecha_desde",
                "fecha_hasta",
                "categoria",
                "moneda",
            ],
        }


def _get_user_id() -> str:
    """Obtiene el user_id desde el contexto de sesión MCP.

    La versión 1.9.x de la librería `mcp` no expone directamente un campo de
    identidad autenticada en el contexto de solicitud.  Como medida provisional
    se lee la variable de entorno ``MCP_USER_ID``.

    Estrategia de evolución:
      Cuando el sistema incorpore autenticación (p.ej., JWT en un transport HTTP),
      este punto de inyección debe leer el claim ``sub`` del token verificado en
      lugar de la variable de entorno.

    Returns
    -------
    str
        Identificador del usuario activo.  Nunca proviene del payload del agente.
    """
    return os.environ.get("MCP_USER_ID", "default_user")


def _make_error(message: str) -> list[types.TextContent]:
    """Crea el contenido de error MCP estándar."""
    return [types.TextContent(type="text", text=message)]


def _make_success(data: dict | list) -> list[types.TextContent]:
    """Serializa una respuesta exitosa como JSON."""
    return [
        types.TextContent(
            type="text",
            text=json.dumps(data, ensure_ascii=False, default=str),
        )
    ]


def _transaction_to_dict(tx: Transaction) -> dict:
    """Convierte una Transaction a diccionario serializable."""
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


# ---------------------------------------------------------------------------
# Bootstrap del servidor
# ---------------------------------------------------------------------------

# Carga de artefactos al inicio (antes del primer request).
_policy: dict = _load_policy(_POLICY_PATH)
_repo: TransactionRepository = TransactionRepository(_DB_PATH)

print(
    f"[finanzas-mcp] Servidor iniciado. DB: '{_DB_PATH}' | Política cargada.",
    file=sys.stderr,
)

# ---------------------------------------------------------------------------
# Instancia del servidor MCP
# ---------------------------------------------------------------------------

server = Server("finanzas-mcp")

# ---------------------------------------------------------------------------
# Registro de herramientas (Requisito 17.1)
# ---------------------------------------------------------------------------

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """Devuelve la lista de las cuatro herramientas disponibles."""
    return [
        types.Tool(
            name="validar_factura",
            description=(
                "Valida los campos de una factura: campos obligatorios (R1), "
                "formato y no-futuro de fecha (R2), moneda CRC/USD (R3), "
                "coherencia aritmética subtotal+IVA=total ±0.01 (R4), "
                "categoría en lista cerrada (R6)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "comercio":  {"type": "string"},
                    "fecha":     {"type": "string"},
                    "total":     {"type": "number"},
                    "moneda":    {"type": "string"},
                    "categoria": {"type": "string"},
                    "subtotal":  {"type": "number"},
                    "iva":       {"type": "number"},
                },
                "required": ["comercio", "fecha", "total", "moneda", "categoria"],
            },
        ),
        types.Tool(
            name="buscar_duplicados",
            description=(
                "Busca transacciones duplicadas para el usuario activo "
                "según comercio, fecha y total. Devuelve como máximo 10 resultados (R5, R9)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "comercio": {"type": "string"},
                    "fecha":    {"type": "string"},
                    "total":    {"type": "number"},
                },
                "required": ["comercio", "fecha", "total"],
            },
        ),
        types.Tool(
            name="listar_transacciones",
            description=(
                "Lista transacciones del usuario activo con filtros controlados. "
                "Aplica lista blanca de filtros y ventana máxima de fechas (R9)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filtros": {
                        "type": "object",
                        "description": (
                            "Solo se permiten claves de la lista blanca: "
                            "comercio, fecha_desde, fecha_hasta, categoria, moneda."
                        ),
                    },
                },
                "required": ["filtros"],
            },
        ),
        types.Tool(
            name="registrar_transaccion",
            description=(
                "Revalida R1–R8 de forma independiente y persiste la transacción "
                "si todo pasa. No requiere tokens de confirmación. "
                "En modo adaptativo del servidor acepta un token automático "
                "('auto:...') solo si la factura es limpia: confianza_ocr (0..1) "
                "alcanza el umbral y contenido_sospechoso es false; si faltan, se "
                "rechaza y se requiere confirmación humana."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "comercio":           {"type": "string"},
                    "fecha":              {"type": "string"},
                    "total":              {"type": "number"},
                    "moneda":             {"type": "string"},
                    "categoria":          {"type": "string"},
                    "subtotal":           {"type": "number"},
                    "iva":                {"type": "number"},
                    "descripcion":        {"type": "string"},
                    "confirmation_token": {"type": "string"},
                    "high_amount_token":  {"type": "string"},
                    "confianza_ocr":        {"type": "number"},
                    "contenido_sospechoso": {"type": "boolean"},
                },
                "required": [
                    "comercio",
                    "fecha",
                    "total",
                    "moneda",
                    "categoria",
                ],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Despachador de herramientas (Requisito 17.4 — isError en error de negocio)
# ---------------------------------------------------------------------------

@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Despacha la llamada a la herramienta correcta y maneja errores de negocio."""

    # Obtenemos user_id desde el contexto de sesión — NUNCA del payload.
    user_id: str = _get_user_id()

    print(
        f"[finanzas-mcp] Llamada a herramienta: '{name}' | user_id: '{user_id}'",
        file=sys.stderr,
    )

    try:
        if name == "validar_factura":
            return await _handle_validar_factura(arguments)

        elif name == "buscar_duplicados":
            return await _handle_buscar_duplicados(arguments, user_id)

        elif name == "listar_transacciones":
            return await _handle_listar_transacciones(arguments, user_id)

        elif name == "registrar_transaccion":
            return await _handle_registrar_transaccion(arguments, user_id)

        else:
            # Herramienta desconocida — error de protocolo, no de negocio.
            print(
                f"[finanzas-mcp] Herramienta desconocida: '{name}'",
                file=sys.stderr,
            )
            raise ValueError(f"Herramienta desconocida: '{name}'")

    except (ValidationError, FilterError, DateRangeError) as exc:
        # Errores de negocio esperados: no deben terminar el servidor (Req. 17.4).
        error_code = getattr(exc, "result", None)
        if error_code is not None:
            code = exc.result.error_code or "BUSINESS_ERROR"
        else:
            code = getattr(exc, "error_code", "BUSINESS_ERROR")

        message = str(exc)
        print(
            f"[finanzas-mcp] Error de negocio [{code}]: {message}",
            file=sys.stderr,
        )
        # La librería mcp.server.Server.call_tool ya envuelve en isError=True
        # cualquier excepción no capturada.  Sin embargo, para garantizar el
        # formato exacto documentado en el diseño (y no depender de ese
        # comportamiento interno), capturamos aquí y relanzamos para que el
        # framework lo serialice correctamente.
        raise

    except Exception as exc:
        # Errores inesperados: loguear a stderr y relanzar (el framework los
        # envuelve en isError=True sin terminar el servidor).
        print(
            f"[finanzas-mcp] Error inesperado en herramienta '{name}': "
            f"{traceback.format_exc()}",
            file=sys.stderr,
        )
        raise


# ---------------------------------------------------------------------------
# Handlers individuales por herramienta
# ---------------------------------------------------------------------------

async def _handle_validar_factura(args: dict) -> list[types.TextContent]:
    """Ejecuta todas las validaciones sobre los datos de una factura.

    No persiste nada.  Devuelve un resultado de validación agregado.
    """
    resultado = evaluar_factura(args)

    if not resultado.valid:
        raise ValidationError(
            ValidationResult(
                is_valid=False,
                errors=resultado.errors,
                error_code=resultado.first_error_code or "VALIDATION_ERROR",
            )
        )

    return _make_success({"is_valid": True, "errors": []})


async def _handle_buscar_duplicados(
    args: dict,
    user_id: str,
) -> list[types.TextContent]:
    """Busca posibles transacciones duplicadas para el usuario activo."""
    comercio = args.get("comercio", "")
    fecha = args.get("fecha", "")
    total = args.get("total", 0.0)

    duplicados = _buscar_duplicados(
        repo=_repo,
        comercio=str(comercio),
        fecha=str(fecha),
        total=float(total),
        user_id=user_id,  # siempre del contexto de sesión
    )

    return _make_success([_transaction_to_dict(tx) for tx in duplicados])


async def _handle_listar_transacciones(
    args: dict,
    user_id: str,
) -> list[types.TextContent]:
    """Lista transacciones del usuario aplicando lista blanca de filtros."""
    filtros: dict = args.get("filtros", {})

    filtros_permitidos: list[str] = _policy.get(
        "allowed_filters",
        ["comercio", "fecha_desde", "fecha_hasta", "categoria", "moneda"],
    )
    max_rango_dias: int = int(_policy.get("max_date_range_days", 90))

    transacciones = _listar_transacciones(
        repo=_repo,
        filtros=filtros,
        user_id=user_id,  # siempre del contexto de sesión
        filtros_permitidos=filtros_permitidos,
        max_rango_dias=max_rango_dias,
    )

    return _make_success([_transaction_to_dict(tx) for tx in transacciones])


async def _handle_registrar_transaccion(
    args: dict,
    user_id: str,
) -> list[types.TextContent]:
    """Revalida R1–R8 y persiste la transacción si todo pasa."""
    # Extraer tokens — no forman parte del payload de datos de la factura.
    token: str | None = args.get("confirmation_token")
    high_amount_token: str | None = args.get("high_amount_token")

    # Construir datos limpios de factura (sin campos de protocolo).
    datos: dict = {
        k: v
        for k, v in args.items()
        if k
        not in {
            "confirmation_token",
            "high_amount_token",
            "user_id",
            "confianza_ocr",
            "contenido_sospechoso",
            "modo_hitl",
            "umbral_confianza_ocr",
        }
    }
    # Ignoramos explícitamente cualquier user_id del payload (Req. 10.3).
    # modo_hitl y umbral_confianza_ocr solo provienen de la política del servidor.

    tx_id = _registrar_transaccion(
        repo=_repo,
        datos=datos,
        token=token,
        high_amount_token=high_amount_token,
        policy=_policy,
        user_id=user_id,  # siempre del contexto de sesión
        confianza_ocr=args.get("confianza_ocr"),
        contenido_sospechoso=args.get("contenido_sospechoso"),
    )

    print(
        f"[finanzas-mcp] Transacción registrada con id={tx_id} para user_id='{user_id}'",
        file=sys.stderr,
    )

    return _make_success({"id": tx_id, "status": "registrada"})


# ---------------------------------------------------------------------------
# Punto de entrada: bucle principal stdio
# ---------------------------------------------------------------------------

async def _main() -> None:
    """Bucle principal del servidor MCP sobre stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Punto de entrada: stdio (defecto) o Streamable HTTP (``--transport streamable-http``)."""
    from mcp_transport import ejecutar

    ejecutar(server, lambda: anyio.run(_main), puerto_defecto=8001)


if __name__ == "__main__":
    main()
