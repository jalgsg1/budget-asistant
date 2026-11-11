# -*- coding: utf-8 -*-
"""Rutas GET /trazas y GET /trazas/{trace_id}."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api_pruebas import trazas
from api_pruebas.esquemas import ErrorEstandar, TrazaResumen

router = APIRouter()


@router.get(
    "/trazas",
    summary="Lista las trazas del usuario configurado",
    response_model=list[TrazaResumen],
    responses={500: {"model": ErrorEstandar}},
)
def listar(request: Request) -> list[dict[str, Any]]:
    config = request.app.state.config
    return trazas.listar_trazas(
        config.traces_dir, config.batch_traces_dir, config.user_id
    )


@router.get(
    "/trazas/{trace_id}",
    summary="Devuelve una traza completa (redactada)",
    response_model=dict[str, Any],
    responses={400: {"model": ErrorEstandar}, 404: {"model": ErrorEstandar}},
)
def obtener(trace_id: str, request: Request) -> dict[str, Any]:
    config = request.app.state.config
    return trazas.leer_traza(
        config.traces_dir, config.batch_traces_dir, config.user_id, trace_id
    )
