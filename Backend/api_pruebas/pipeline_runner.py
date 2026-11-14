# -*- coding: utf-8 -*-
"""
api_pruebas/pipeline_runner.py — Ejecución del Pipeline con respuestas guionadas.

Nunca importa ``mcp``.
"""

from __future__ import annotations

from typing import Optional, Sequence

from agent.agent import InvoicePipeline, ToolError
from api_pruebas.config import Config
from api_pruebas.errores import ErrorApi, mapear_excepcion, redactar
from api_pruebas.esquemas import PipelineRespuesta
from api_pruebas.mcp_remoto import herramientas_pipeline
from api_pruebas.servicios import ServiciosNegocio
from ocr_mcp.ocr_core import OcrToolError, validar_ruta


class ScriptedIO:
    """Implementa ``UserIO``: entrega respuestas en orden y ``None`` al agotarse."""

    def __init__(self, respuestas: Sequence[str]) -> None:
        self._respuestas = list(respuestas)
        self._indice = 0
        self.prompts: list[str] = []
        self.mensajes: list[str] = []

    def ask(self, prompt: str) -> Optional[str]:
        self.prompts.append(prompt)
        if self._indice >= len(self._respuestas):
            return None
        respuesta = self._respuestas[self._indice]
        self._indice += 1
        return respuesta

    def notify(self, message: str) -> None:
        self.mensajes.append(message)


def ejecutar_pipeline(
    servicios: ServiciosNegocio,
    config: Config,
    ruta: str,
    respuestas: Sequence[str],
) -> PipelineRespuesta:
    """Ejecuta el Pipeline para ``ruta``; cualquier status responde normalmente.

    Lanza ``ErrorApi`` (400/502/...) si la ruta es inválida o si un ``ToolError``
    escapa de ``run``.
    """
    # 4.4: validar antes de crear el Pipeline.
    try:
        validar_ruta(ruta, str(config.invoices_dir), config.max_upload_bytes)
    except OcrToolError as exc:
        status, code, msg = mapear_excepcion(exc)
        raise ErrorApi(status, code, msg) from None

    io = ScriptedIO(respuestas)
    try:
        with herramientas_pipeline(servicios, config) as tools:
            pipeline = InvoicePipeline(
                tools, io, config.policy, config.user_id, str(config.traces_dir)
            )
            result = pipeline.run(ruta)
    except ToolError as exc:
        status, code, msg = mapear_excepcion(exc)
        raise ErrorApi(status, code, msg) from None

    trace_id = result.trace.trace_id if result.trace is not None else ""
    return PipelineRespuesta(
        status=result.status,
        termination_reason=result.termination_reason,
        transaction_id=result.transaction_id,
        trace_id=trace_id,
        mensajes=redactar(list(io.mensajes)),
        prompts=redactar(list(io.prompts)),
    )
