"""Pruebas de propiedad y ejemplos para alertas y decisión HITL.

Spec: evaluacion-experimental-paper (tarea 4.2, requisito 19.1).
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from agent.hitl import (
    ALERTAS,
    CAMPOS_REQUERIDOS,
    RAZON_LIMPIA,
    RAZON_SIEMPRE,
    EntradaAlertas,
    decidir_hitl,
    evaluar_alertas,
)

_conf = st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
_monto = st.one_of(
    st.none(), st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False)
)
_moneda = st.one_of(st.none(), st.sampled_from(["CRC", "USD", "EUR"]))


@st.composite
def entradas(draw) -> EntradaAlertas:
    campos = {
        c: draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
        for c in CAMPOS_REQUERIDOS
        if draw(st.booleans())
    }
    umbrales = {
        m: draw(st.floats(min_value=1.0, max_value=1e6, allow_nan=False))
        for m in ("CRC", "USD")
        if draw(st.booleans())
    }
    return EntradaAlertas(
        confianza_global=draw(_conf),
        confianza_campos=campos,
        ocr_bajo_legado=draw(st.booleans()),
        umbral_confianza_ocr=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        total=draw(_monto),
        moneda=draw(_moneda),
        umbrales_monto=umbrales,
        n_duplicados=draw(st.integers(min_value=0, max_value=5)),
        contenido_sospechoso=draw(st.booleans()),
    )


def _oraculo(e: EntradaAlertas) -> tuple[str, ...]:
    u = e.umbral_confianza_ocr
    confs = [e.confianza_global] + [e.confianza_campos.get(c) for c in CAMPOS_REQUERIDOS]
    bajo = e.ocr_bajo_legado or any(c is not None and c < u for c in confs)
    alto = (
        e.total is not None
        and e.moneda in e.umbrales_monto
        and e.total > e.umbrales_monto[e.moneda]
    )
    flags = [bajo, alto, e.n_duplicados > 0, e.contenido_sospechoso]
    return tuple(a for a, f in zip(ALERTAS, flags) if f)


def _base(**kw) -> EntradaAlertas:
    datos = dict(
        confianza_global=0.99,
        confianza_campos={},
        ocr_bajo_legado=False,
        umbral_confianza_ocr=0.8,
        total=100.0,
        moneda="USD",
        umbrales_monto={"USD": 1000.0},
        n_duplicados=0,
        contenido_sospechoso=False,
    )
    datos.update(kw)
    return EntradaAlertas(**datos)


# ---------------------------------------------------------------- Property 5
@settings(max_examples=100)
@given(entradas())
def test_property_5_evaluacion_determinista_de_alertas(e):
    """**Validates: Requirements 4.3, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8**"""
    r1 = evaluar_alertas(e)
    assert r1 == _oraculo(e)
    assert r1 == evaluar_alertas(e)


# ---------------------------------------------------------------- Property 6
@settings(max_examples=100)
@given(
    st.sampled_from(["siempre", "adaptativo"]),
    st.lists(st.sampled_from(ALERTAS), unique=True, max_size=len(ALERTAS)),
)
def test_property_6_decision_coherente_con_modo_y_alertas(modo, alertas):
    """**Validates: Requirements 5.1, 5.7, 8.1, 8.2, 8.3, 8.4**"""
    d = decidir_hitl(modo, alertas)
    assert 0 <= len(d.reglas_detonantes) <= 50
    assert all(1 <= len(r) <= 100 for r in d.reglas_detonantes)
    assert 1 <= len(d.razon) <= 500
    assert d.modo_hitl == modo
    if modo == "siempre":
        assert d.hitl_solicitado is True
        assert d.razon == RAZON_SIEMPRE == "modo_hitl=siempre"
    elif not alertas:
        assert d.hitl_solicitado is False
        assert d.reglas_detonantes == ()
        assert d.razon == RAZON_LIMPIA
    else:
        assert d.hitl_solicitado is True
        assert set(alertas) <= set(d.reglas_detonantes)
        assert all(a in d.razon for a in alertas)


# ------------------------------------------------- Ejemplos por alerta (19.1)
def test_ejemplo_factura_limpia_sin_alertas():
    assert evaluar_alertas(_base()) == ()


def test_ejemplo_low_ocr_confidence():
    assert evaluar_alertas(_base(confianza_global=0.5)) == ("LOW_OCR_CONFIDENCE",)
    assert evaluar_alertas(_base(confianza_campos={"total": 0.1})) == ("LOW_OCR_CONFIDENCE",)


def test_ejemplo_high_amount():
    e = _base(total=5000.0)
    assert evaluar_alertas(e) == ("HIGH_AMOUNT",)


def test_ejemplo_possible_duplicate():
    assert evaluar_alertas(_base(n_duplicados=2)) == ("POSSIBLE_DUPLICATE",)


def test_ejemplo_suspicious_content():
    assert evaluar_alertas(_base(contenido_sospechoso=True)) == ("SUSPICIOUS_CONTENT",)
