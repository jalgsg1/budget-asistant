"""Pruebas de propiedad de la traza común (Req. 11.5, 11.6, 11.9, 11.10)."""
import json
import tempfile
from types import SimpleNamespace

import pytest
from hypothesis import given, settings, strategies as st

from baseline.traza_comun import (
    CAMPOS,
    ESTADOS_FINALES,
    TrazaComun,
    desde_traza_agente,
    escribir_traza,
)

_texto = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=60)
_tokens = st.integers(min_value=0, max_value=10**9)
_duracion = st.floats(min_value=0, max_value=1e9, allow_nan=False, allow_infinity=False)

_trazas = st.builds(
    TrazaComun,
    sistema=_texto,
    ruta_factura=_texto,
    tokens_entrada=_tokens,
    tokens_salida=_tokens,
    duracion_ms=_duracion,
    estado_final=st.sampled_from(ESTADOS_FINALES),
    registro_en_bd=st.booleans(),
)

_MAPEO = {
    "success": "registrada",
    "validation_error": "rechazada",
    "user_abort": "usuario_rechazo",
    "step_limit": "limite",
    "token_limit": "limite",
}


# Feature: evaluacion-experimental-paper, Property 13: Traza_Comun mantiene forma y round trip
@settings(max_examples=100, deadline=None)
@given(traza=_trazas)
def test_property_13_forma_y_round_trip(traza):
    """**Validates: Requirements 11.5, 11.6, 11.10**"""
    d = traza.a_dict()
    assert tuple(d.keys()) == CAMPOS
    assert set(d) == set(CAMPOS) and len(d) == 7

    with tempfile.TemporaryDirectory() as tmp:
        ruta = escribir_traza(traza, tmp)
        assert ruta is not None
        with open(ruta, encoding="utf-8") as fh:
            leido = json.load(fh)
    assert set(leido) == set(CAMPOS)
    assert TrazaComun.desde_dict(leido) == traza


@settings(max_examples=100, deadline=None)
@given(traza=_trazas, estado=_texto.filter(lambda s: s not in ESTADOS_FINALES))
def test_property_13_rechaza_estado_invalido(traza, estado):
    """**Validates: Requirements 11.5, 11.6, 11.10**"""
    d = traza.a_dict()
    d["estado_final"] = estado
    with pytest.raises(ValueError):
        TrazaComun.desde_dict(d)


# Feature: evaluacion-experimental-paper, Property 14: conversión de la traza del agente
@settings(max_examples=100, deadline=None)
@given(
    status=st.sampled_from(sorted(_MAPEO)),
    ruta=_texto,
    t_in=_tokens,
    t_out=_tokens,
    duracion=_duracion,
    registro=st.booleans(),
)
def test_property_14_conversion_agente(status, ruta, t_in, t_out, duracion, registro):
    """**Validates: Requirements 11.9**"""
    resultado = SimpleNamespace(
        status=status,
        trace=SimpleNamespace(image_path=ruta, tokens_entrada=t_in, tokens_salida=t_out),
    )
    traza = desde_traza_agente(resultado, duracion, registro)
    assert isinstance(traza, TrazaComun)
    assert traza.estado_final == _MAPEO[status]
    assert traza.sistema == "arquitectura_mcp"
    assert traza.ruta_factura == ruta
    assert traza.tokens_entrada == t_in and traza.tokens_salida == t_out
    assert traza.duracion_ms == duracion
    assert traza.registro_en_bd is registro
    assert TrazaComun.desde_dict(traza.a_dict()) == traza
