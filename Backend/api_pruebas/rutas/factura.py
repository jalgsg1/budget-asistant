# -*- coding: utf-8 -*-
"""POST /validar — evaluación de las reglas de factura (R1, R2, R3, R4, R6)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from api_pruebas.errores import ErrorEstandar, redactar
from api_pruebas.esquemas import FacturaIn, ReglaResultado, ValidacionRespuesta

router = APIRouter()


@router.post(
    "/validar",
    summary="Validar los datos de una factura",
    response_model=ValidacionRespuesta,
    responses={
        422: {"model": ErrorEstandar, "description": "Cuerpo de la solicitud inválido"},
    },
)
def validar(request: Request, factura: FacturaIn) -> ValidacionRespuesta:
    servicios = request.app.state.servicios
    resultado = servicios.validar(factura.model_dump(exclude_none=True))
    reglas = [
        ReglaResultado(
            regla=r.regla,
            valid=r.valid,
            code=r.code,
            message=redactar(r.message),
        )
        for r in resultado.reglas
    ]
    return ValidacionRespuesta(valid=resultado.valid, reglas=reglas)
