# -*- coding: utf-8 -*-
"""Ruta POST /pipeline/run."""

from __future__ import annotations

from fastapi import APIRouter, Request

from api_pruebas import pipeline_runner
from api_pruebas.esquemas import ErrorEstandar, PipelineIn, PipelineRespuesta

router = APIRouter()


@router.post(
    "/pipeline/run",
    summary="Ejecuta el Pipeline de procesamiento de una factura",
    response_model=PipelineRespuesta,
    responses={
        400: {"model": ErrorEstandar},
        422: {"model": ErrorEstandar},
        502: {"model": ErrorEstandar},
    },
)
def ejecutar(cuerpo: PipelineIn, request: Request) -> PipelineRespuesta:
    return pipeline_runner.ejecutar_pipeline(
        request.app.state.servicios,
        request.app.state.config,
        cuerpo.ruta,
        cuerpo.respuestas,
    )
