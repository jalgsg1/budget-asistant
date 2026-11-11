# -*- coding: utf-8 -*-
"""Rutas POST /test/reset y POST /test/seed (solo Modo_Pruebas)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from api_pruebas import modo_pruebas
from api_pruebas.esquemas import ErrorEstandar, ResetRespuesta, SeedIn, SeedRespuesta

router = APIRouter()


@router.post(
    "/test/reset",
    summary="Elimina las transacciones del usuario configurado (solo pruebas)",
    response_model=ResetRespuesta,
    responses={403: {"model": ErrorEstandar}},
)
def reset(request: Request) -> ResetRespuesta:
    config = request.app.state.config
    modo_pruebas.verificar_permiso(config)
    eliminadas = request.app.state.servicios.reset()
    return ResetRespuesta(eliminadas=eliminadas)


@router.post(
    "/test/seed",
    summary="Inserta transacciones de prueba (solo pruebas)",
    response_model=SeedRespuesta,
    responses={
        403: {"model": ErrorEstandar},
        422: {"model": ErrorEstandar},
    },
)
def seed(request: Request, cuerpo: Optional[SeedIn] = None) -> SeedRespuesta:
    config = request.app.state.config
    modo_pruebas.verificar_permiso(config)
    if cuerpo is None or cuerpo.transacciones is None:
        items = modo_pruebas.seed_ejemplo()
    else:
        items = cuerpo.transacciones
    insertadas = request.app.state.servicios.seed(items)
    return SeedRespuesta(insertadas=insertadas)
