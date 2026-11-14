# -*- coding: utf-8 -*-
"""
CLI de gestor-facturas (Tarea 12).

Uso::

    python -m agent.main RUTA_IMAGEN

* Los prompts del agente se escriben a stdout y las respuestas se leen de stdin
  (R19.2).
* El resultado final (éxito, error de validación, razón de parada) se imprime
  en la salida CLI (R19.3).
* Toda la entrada es por argumentos o prompts CLI (R19.1).

``mcp`` se importa de forma diferida: este módulo se puede importar (y probar
con herramientas inyectadas) aunque ``mcp`` no esté usable en el entorno.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent.agent import InvoicePipeline, PipelineResult, Policy, load_policy
from finanzas_mcp.business.hitl import PoliticaHitlError

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = BACKEND_DIR / "politica.json"
DEFAULT_SKILL_PATH = BACKEND_DIR / "agent" / "SKILL.md"
DEFAULT_TRACES_DIR = BACKEND_DIR / "traces"

_EXIT_CODES = {"success": 0, "validation_error": 1, "user_abort": 2,
               "step_limit": 3, "token_limit": 3}


#: código de salida por política HITL inválida (antes de procesar documentos)
EXIT_POLICY = 2

#: código de salida por uso incorrecto (falta la ruta de la imagen); EX_USAGE
EXIT_USAGE = 64

USAGE_DOCKER = (
    "Error: falta la ruta de la imagen de la factura.\n"
    "Uso con Docker:\n"
    "  docker compose run --rm gestor-facturas python -m agent.main "
    "/app/facturas/mi_factura.jpg"
)


def _resolve_image_path(image_path: Optional[str], stdin: Any, stdout: Any) -> Optional[str]:
    """Devuelve la ruta dada; si falta y stdin es TTY la pregunta; si no, ``None``."""
    if image_path:
        return image_path
    isatty = getattr(stdin, "isatty", None)
    if not callable(isatty) or not isatty():
        return None
    answer = ConsoleIO(stdin, stdout).ask(
        "Ruta de la imagen de la factura (ej. /app/facturas/mi_factura.jpg):"
    )
    answer = (answer or "").strip()
    return answer or None


def _force_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------------------
# UserIO de consola
# ---------------------------------------------------------------------------


class ConsoleIO:
    """``UserIO`` sobre stdout/stdin.  EOF se interpreta como "sin respuesta"."""

    def __init__(self, stdin=None, stdout=None) -> None:
        self._in = stdin if stdin is not None else sys.stdin
        self._out = stdout if stdout is not None else sys.stdout

    def ask(self, prompt: str) -> Optional[str]:
        self._out.write(prompt if prompt.endswith((" ", "\n")) else prompt + " ")
        self._out.flush()
        line = self._in.readline()
        if line == "":  # EOF
            self._out.write("\n")
            self._out.flush()
            return None
        return line.rstrip("\r\n")

    def notify(self, message: str) -> None:
        self._out.write(message + "\n")
        self._out.flush()


# ---------------------------------------------------------------------------
# Adaptador de herramientas sobre clientes MCP stdio
# ---------------------------------------------------------------------------

#: herramienta -> servidor que la expone
TOOL_SERVERS = {
    "ocr_imagen": "ocr-mcp",
    "validar_factura": "finanzas-mcp",
    "buscar_duplicados": "finanzas-mcp",
    "listar_transacciones": "finanzas-mcp",
    "registrar_transaccion": "finanzas-mcp",
}


#: servidor -> variable de entorno con la URL Streamable HTTP (vacía = stdio local)
MCP_URL_VARS = {"ocr-mcp": "OCR_MCP_URL", "finanzas-mcp": "FINANZAS_MCP_URL"}


def mcp_url(server: str) -> str:
    """URL Streamable HTTP configurada para ``server`` ('' si debe usarse stdio)."""
    return (os.environ.get(MCP_URL_VARS[server]) or "").strip()


def mcp_http_configurado() -> bool:
    """Verdadero si hay URL HTTP para algún servidor MCP."""
    return any(mcp_url(s) for s in MCP_URL_VARS)


def _server_params(module: str, extra_env: Mapping[str, str]):
    from mcp import StdioServerParameters  # import diferido

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **extra_env}
    return StdioServerParameters(
        command=sys.executable, args=["-m", module], env=env, cwd=str(BACKEND_DIR),
    )


def _result_to_raw(result: Any) -> Any:
    """Convierte ``CallToolResult`` al formato que entiende ``normalize_tool_result``."""
    texts = [getattr(c, "text", "") for c in (result.content or []) if getattr(c, "type", "") == "text"]
    text = "\n".join(texts)
    if getattr(result, "isError", False):
        return {"isError": True, "content": [{"type": "text", "text": text}]}
    return text


class McpToolbox:
    """Mantiene sesiones stdio con ocr-mcp y finanzas-mcp en un hilo con su propio
    event loop y expone ``tools``: ``{nombre: callable(dict) -> resultado}`` síncronos.
    """

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._stack: Optional[AsyncExitStack] = None
        self._task: Optional["asyncio.Future[None]"] = None
        self._stop: Optional[asyncio.Event] = None
        self._sessions: dict[str, Any] = {}
        self.tools: dict[str, Callable[[dict], Any]] = {}

    def __enter__(self) -> "McpToolbox":
        self._thread.start()
        try:
            self._run(self._start())
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _open(self) -> None:
        from mcp import ClientSession  # import diferido
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        self._stack = AsyncExitStack()
        specs = {
            "ocr-mcp": ("ocr_mcp.server", {}),
            "finanzas-mcp": ("finanzas_mcp.server", {"MCP_USER_ID": self._user_id}),
        }
        for name, (module, env) in specs.items():
            url = mcp_url(name)
            if url:
                # Streamable HTTP: el servidor ya corre (p. ej. docker compose up).
                read, write, _ = await self._stack.enter_async_context(
                    streamablehttp_client(url)
                )
            else:
                read, write = await self._stack.enter_async_context(
                    stdio_client(_server_params(module, env))
                )
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[name] = session
        for tool, server in TOOL_SERVERS.items():
            self.tools[tool] = self._make_caller(server, tool)

    def _make_caller(self, server: str, tool: str) -> Callable[[dict], Any]:
        def call(args: dict) -> Any:
            async def _go():
                return await self._sessions[server].call_tool(tool, args)
            return _result_to_raw(self._run(_go()))
        return call

    async def _start(self) -> None:
        self._stop = asyncio.Event()
        ready = self._loop.create_future()
        self._task = asyncio.ensure_future(self._lifecycle(ready))
        await ready

    async def _lifecycle(self, ready: "asyncio.Future[None]") -> None:
        """Abre y cierra las sesiones MCP en una única tarea.

        Los transportes (anyio task groups) exigen que entrar y salir de sus
        contextos ocurra en la misma tarea.
        """
        try:
            await self._open()
            ready.set_result(None)
            await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc)
        finally:
            if self._stack is not None:
                try:
                    await self._stack.aclose()
                except BaseException as exc:  # cierre best-effort
                    print(f"[agent] Aviso al cerrar MCP: {exc}", file=sys.stderr)
                self._stack = None

    async def _shutdown(self) -> None:
        self._stop.set()
        await self._task

    def close(self) -> None:
        if self._task is not None and self._loop.is_running():
            try:
                self._run(self._shutdown())
            except BaseException as exc:  # cierre best-effort
                print(f"[agent] Aviso al cerrar MCP: {exc}", file=sys.stderr)
            self._task = None
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def _read_skill(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def run_cli(
    image_path: str,
    tools: Mapping[str, Callable[[dict], Any]],
    io: Any = None,
    policy: Optional[Policy] = None,
    user_id: Optional[str] = None,
    traces_dir: Optional[str] = None,
) -> PipelineResult:
    """Ejecuta el pipeline con herramientas ya construidas (inyectable en pruebas)."""
    policy = policy or load_policy(str(DEFAULT_POLICY_PATH))
    io = io or ConsoleIO()
    pipeline = InvoicePipeline(
        tools=tools, io=io, policy=policy,
        user_id=user_id or os.environ.get("MCP_USER_ID", "default_user"),
        traces_dir=traces_dir if traces_dir is not None else str(DEFAULT_TRACES_DIR),
    )
    return pipeline.run(image_path)


def main(image_path: Optional[str] = None, argv: Optional[Sequence[str]] = None) -> int:
    """Punto de entrada CLI.  Devuelve el código de salida del proceso."""
    _force_utf8()
    if image_path is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent.main",
            description="Procesa una imagen de factura y la registra tras confirmación.",
        )
        parser.add_argument(
            "image_path", nargs="?", default=None,
            help="Ruta de la imagen de factura (dentro de INVOICES_DIR)",
        )
        image_path = parser.parse_args(argv).image_path

    image_path = _resolve_image_path(image_path, sys.stdin, sys.stdout)
    if image_path is None:
        print(USAGE_DOCKER, file=sys.stderr)
        return EXIT_USAGE

    try:
        policy = load_policy(str(DEFAULT_POLICY_PATH))
    except PoliticaHitlError as exc:
        print(f"Error: política HITL inválida en politica.json: {exc}", file=sys.stderr)
        return EXIT_POLICY
    except (OSError, ValueError) as exc:
        print(f"Error: no se pudo cargar politica.json: {exc}", file=sys.stderr)
        return 1
    skill = _read_skill(DEFAULT_SKILL_PATH)
    if not skill:
        print("Aviso: SKILL.md no disponible; se usa el pipeline integrado.", file=sys.stderr)

    user_id = os.environ.get("MCP_USER_ID", "default_user")
    try:
        with McpToolbox(user_id) as box:
            result = run_cli(image_path, box.tools, ConsoleIO(), policy, user_id)
    except ImportError as exc:
        print(f"Error: el paquete 'mcp' no está disponible: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # fallo de arranque/transporte MCP
        print(f"Error al iniciar o usar los servidores MCP: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Resultado: {result.status} (razón: {result.termination_reason})")
    if result.transaction_id is not None:
        print(f"ID de transacción: {result.transaction_id}")
    return _EXIT_CODES.get(result.status, 1)


if __name__ == "__main__":
    sys.exit(main())
