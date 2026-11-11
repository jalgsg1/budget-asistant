# -*- coding: utf-8 -*-
"""Aplicación FastAPI de la API_Pruebas.

``app`` se crea sin leer la configuración: ésta se carga en el ``lifespan``,
así que importar este módulo no falla si falta ``MCP_USER_ID``. No importa ``mcp``.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from api_pruebas import errores
from api_pruebas.config import Config, cargar_config
from api_pruebas.rutas import batch, factura, ocr, pipeline, transacciones, trazas
from api_pruebas.servicios import ExtractorOcr, ServiciosNegocio

logger = logging.getLogger("api_pruebas")

_HOSTS_LOCALES = ("127.0.0.1", "localhost")


def host_es_local(host: str) -> bool:
    """Verdadero solo para 127.0.0.1 y localhost."""
    return (host or "").strip().lower() in _HOSTS_LOCALES


def advertencia_red(host: str) -> Optional[str]:
    """Texto de advertencia si ``host`` expone la API en la red; None si es local."""
    if host_es_local(host):
        return None
    return (
        f"ADVERTENCIA: la API_Pruebas escucha en {host}, expuesta en la red. "
        "No tiene autenticación; use 127.0.0.1 salvo que sea imprescindible."
    )


def _poblar_estado(app: FastAPI, config: Config, extractor_ocr: Optional[ExtractorOcr]) -> None:
    app.state.config = config
    app.state.servicios = ServiciosNegocio(config, extractor_ocr)


def crear_app(
    config: Optional[Config] = None, extractor_ocr: Optional[ExtractorOcr] = None
) -> FastAPI:
    """Construye la aplicación. Con ``config`` explícito el estado se puebla de inmediato."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        errores.configurar_logging()
        if getattr(app.state, "config", None) is None:
            _poblar_estado(app, cargar_config(), extractor_ocr)  # ConfigError si falta MCP_USER_ID
        # Mejor esfuerzo: el host real lo decide el lanzador (--host) o API_HOST.
        aviso = advertencia_red(os.environ.get("API_HOST", "127.0.0.1"))
        if aviso:
            logger.warning(aviso)
        yield

    app = FastAPI(
        title="API_Pruebas",
        description="Capa HTTP de pruebas sobre los servicios de negocio.",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    errores.registrar_handlers(app)
    for modulo in (ocr, factura, transacciones, pipeline, batch, trazas):
        app.include_router(modulo.router)

    if config is not None:
        _poblar_estado(app, config, extractor_ocr)
    return app


app = crear_app()
