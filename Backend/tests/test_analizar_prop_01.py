# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 1: Partición de campos.

**Validates: Requirements 1.2, 2.1, 2.2, 2.3**
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from api_pruebas.config import cargar_config
from api_pruebas.servicios import CAMPOS_FACTURA, ServiciosNegocio, CLOSED_CATEGORY_LIST
from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

_AUSENTE = object()

_texto = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\x00"),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")

_vacios = st.sampled_from([None, "", " ", "   ", "\t", "\n "])

_valores = {
    "comercio": _texto,
    "fecha": st.dates().map(lambda d: d.isoformat()),
    "total": st.one_of(st.floats(min_value=0.01, max_value=1e6, allow_nan=False), _texto),
    "moneda": st.sampled_from(["CRC", "USD", "EUR"]),
    "categoria": st.sampled_from(list(CLOSED_CATEGORY_LIST)),
    "subtotal": st.floats(min_value=0.01, max_value=1e6, allow_nan=False),
    "iva": st.floats(min_value=0, max_value=1e5, allow_nan=False),
    "descripcion": _texto,
}


@st.composite
def _salidas_ocr(draw):
    payload: dict = {}
    for nombre in CAMPOS_FACTURA:
        valor = draw(st.one_of(st.just(_AUSENTE), _vacios, _valores[nombre]))
        if valor is not _AUSENTE:
            payload[nombre] = valor
    extras = draw(
        st.dictionaries(
            st.text(min_size=1, max_size=8).filter(lambda k: k not in CAMPOS_FACTURA),
            st.one_of(st.none(), st.integers(), _texto),
            max_size=3,
        )
    )
    return {**extras, **payload}


def _presente(valor) -> bool:
    return valor is not None and not (isinstance(valor, str) and not valor.strip())


@pytest.fixture()
def config(tmp_path):
    return cargar_config(
        {
            "MCP_USER_ID": "usuario_test",
            "DB_PATH": str(tmp_path / "t.db"),
            "INVOICES_DIR": str(tmp_path / "facturas"),
            "TRACES_DIR": str(tmp_path / "traces"),
        }
    )


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(payload=_salidas_ocr())
def test_particion_de_campos(config, payload):
    """Feature: invoice-analyze-api, Property 1: Partición de campos."""
    ocr = FakeOcr(OcrResult(text=json.dumps(payload), confidence=1.0))
    servicios = ServiciosNegocio(config, ocr)

    resp = servicios.analizar_subida("factura.png", PNG)

    campos = set(resp.campos)
    no_ident = resp.campos_no_identificados
    # Cada Campo_Factura aparece en exactamente uno de los dos contenedores.
    assert campos.isdisjoint(no_ident)
    assert len(no_ident) == len(set(no_ident))
    assert campos | set(no_ident) == set(CAMPOS_FACTURA)
    # campos: solo valores no nulos ni vacíos; no_identificados: exactamente el resto.
    esperados = {n for n in CAMPOS_FACTURA if _presente(payload.get(n))}
    assert campos == esperados
    assert set(no_ident) == set(CAMPOS_FACTURA) - esperados
    # Orden de CAMPOS_FACTURA y sin claves ajenas.
    assert no_ident == [n for n in CAMPOS_FACTURA if n in set(no_ident)]
    assert list(resp.campos) == [n for n in CAMPOS_FACTURA if n in campos]
    assert ocr.n_llamadas == 1
