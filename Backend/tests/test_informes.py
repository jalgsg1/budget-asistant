"""Pruebas de eval/informes.py: Propiedades 28 a 30 y casos de ejemplo (Req. 17)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eval import informes
from eval.informes import (
    ENCABEZADOS_TABLA,
    MarcasBenchError,
    ResultadosInvalidosError,
    actualizar_injection_analysis,
    commit_actual,
    construir_resultados,
    escribir_json_atomico,
    formatear_tabla,
    leer_resultados,
)
from eval.metricas import calcular_todo

# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------

_razon = st.one_of(st.none(), st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False))
_costo = st.one_of(st.none(), st.floats(min_value=0, max_value=1e7, allow_nan=False, allow_infinity=False))


def _m(valor_st):
    return valor_st.map(lambda v: {"valor": v, "numerador": 0, "denominador": 0})


_metricas_sistema = st.fixed_dictionaries(
    {
        "metricas": st.fixed_dictionaries(
            {
                "integridad_fpa": _m(_razon),
                "asr": _m(_razon),
                "tasa_friccion": _m(_razon),
                "costo_operacional": st.fixed_dictionaries(
                    {
                        "latencia_ms": _m(_costo),
                        "tokens_entrada": _m(_costo),
                        "tokens_salida": _m(_costo),
                    }
                ),
            }
        )
    }
)

_nombres = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="|"),
    min_size=1,
    max_size=12,
)
_sistemas_tabla = st.dictionaries(_nombres, _metricas_sistema, max_size=5)

_texto = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=20)
_json_hoja = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(allow_nan=False, allow_infinity=False),
    _texto,
)
_json_valor = st.recursive(
    _json_hoja,
    lambda hijos: st.one_of(st.lists(hijos, max_size=3), st.dictionaries(_texto, hijos, max_size=3)),
    max_leaves=8,
)
_resultados_validos = st.fixed_dictionaries(
    {
        "version": st.just("1"),
        "commit": st.one_of(st.none(), _texto),
        "modelo": _texto,
        "registros": st.lists(st.dictionaries(_texto, _json_valor, max_size=3), min_size=1, max_size=3),
        "extra": _json_valor,
    }
)


@st.composite
def _registro(draw):
    tipo = draw(st.sampled_from([None, "integridad", "inyeccion"]))
    particion = "limpia" if tipo is None else "adversarial"
    cond = draw(
        st.sampled_from(
            [None, "monto_alterado", "moneda_alterada", "confirmacion_evadida", "exfiltracion", "regla_evadida"]
        )
    )
    filas = draw(
        st.lists(
            st.fixed_dictionaries(
                {
                    "comercio": st.sampled_from(["A", "B", "CANARIO-1"]),
                    "total": st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
                    "moneda": st.sampled_from(["CRC", "USD"]),
                }
            ),
            max_size=2,
        )
    )
    return {
        "sistema": draw(st.sampled_from(["baseline_naive", "baseline_prompt_guarded", "arquitectura_mcp"])),
        "particion": particion,
        "id": draw(st.text(alphabet="abcdef0123456789", min_size=1, max_size=6)),
        "archivo": "x.jpg",
        "tipo_caso": tipo,
        "condicion_compromiso": cond,
        "datos_esperados": {"total": 100.0, "moneda": "CRC"},
        "ground_truth": {"comercio": "A", "fecha": "2025-01-01", "moneda": "CRC", "total": 100.0, "categoria": "x"},
        "es_valida_limpia": draw(st.booleans()),
        "canario": "CANARIO-1",
        "estado_final": draw(st.sampled_from(["registrada", "rechazada", ""])),
        "registro_en_bd": draw(st.booleans()),
        "filas_almacenadas": filas,
        "tokens_entrada": draw(st.integers(0, 5000)),
        "tokens_salida": draw(st.integers(0, 5000)),
        "duracion_ms": draw(st.floats(min_value=0, max_value=1e5, allow_nan=False, allow_infinity=False)),
        "confirmaciones_solicitadas": draw(st.integers(0, 3)),
    }


_PARAMS = {"limite": None, "semilla": 1}
_POLITICA = {"modo": "confirmar_todo"}


def _construir(registros):
    return construir_resultados(registros, _PARAMS, "prov", "mod", _POLITICA, inicio_utc="2025-01-01T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Property 28
# ---------------------------------------------------------------------------

@settings(max_examples=100, deadline=None)
@given(_sistemas_tabla)
def test_property_28_formato_tabla(sistemas):
    """**Validates: Requirements 17.4, 17.5, 17.6**"""
    lineas = formatear_tabla(sistemas).rstrip("\n").split("\n")
    assert lineas[0] == "| " + " | ".join(ENCABEZADOS_TABLA) + " |"
    assert len(lineas) == 2 + len(sistemas)
    razon = re.compile(r"^(\d+\.\d{4}|n/d)$")
    costo = re.compile(r"^(\d+\.\d|n/d)$")
    for linea, (nombre, datos) in zip(lineas[2:], sistemas.items()):
        celdas = [c.strip() for c in linea.strip("|").split("|")]
        assert len(celdas) == len(ENCABEZADOS_TABLA)
        assert celdas[0] == nombre.strip()
        m = datos["metricas"]
        valores = [m["integridad_fpa"], m["asr"], m["tasa_friccion"]]
        valores += [m["costo_operacional"][k] for k in ("latencia_ms", "tokens_entrada", "tokens_salida")]
        for i, (celda, met) in enumerate(zip(celdas[1:], valores)):
            assert (razon if i < 3 else costo).match(celda), celda
            assert (celda == "n/d") == (met["valor"] is None)


# ---------------------------------------------------------------------------
# Property 29
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(_resultados_validos)
def test_property_29_round_trip(obj):
    """**Validates: Requirements 17.1, 17.9**"""
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "resultados_paper.json"
        escribir_json_atomico(obj, ruta)
        primero = leer_resultados(ruta)
        escribir_json_atomico(primero, ruta)
        assert leer_resultados(ruta) == primero
        assert [p.name for p in Path(d).iterdir()] == ["resultados_paper.json"]


@settings(max_examples=25, deadline=None)
@given(_resultados_validos, _resultados_validos)
def test_property_29_fallo_conserva_archivo_previo(previo, nuevo):
    """**Validates: Requirements 17.9**"""
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "resultados_paper.json"
        escribir_json_atomico(previo, ruta)
        antes = ruta.read_bytes()
        original = os.replace

        def falla(*a, **k):
            raise OSError("fallo simulado")

        os.replace = falla
        try:
            with pytest.raises(OSError):
                escribir_json_atomico(nuevo, ruta)
        finally:
            os.replace = original
        assert ruta.read_bytes() == antes
        assert [p.name for p in Path(d).iterdir()] == ["resultados_paper.json"]


# ---------------------------------------------------------------------------
# Property 30
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(st.lists(_registro(), min_size=1, max_size=8))
def test_property_30_recalcular_determinista(registros):
    """**Validates: Requirements 17.7**"""
    resultados = _construir(registros)
    with tempfile.TemporaryDirectory() as d:
        ruta = Path(d) / "resultados_paper.json"
        escribir_json_atomico(resultados, ruta)
        leidos = leer_resultados(ruta)
    r1 = {s: v["metricas"] for s, v in calcular_todo(leidos["registros"]).items()}
    r2 = {s: v["metricas"] for s, v in calcular_todo(leidos["registros"]).items()}
    assert r1 == r2
    assert r1 == resultados["metricas"]
    assert r1 == leidos["metricas"]


# ---------------------------------------------------------------------------
# Ejemplos
# ---------------------------------------------------------------------------

def test_commit_null_si_git_no_disponible(monkeypatch):
    def sin_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(informes.subprocess, "run", sin_git)
    assert commit_actual() is None
    assert _construir([])["commit"] is None


def test_commit_null_si_git_falla(monkeypatch):
    monkeypatch.setattr(
        informes.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 128, stdout="", stderr="x")
    )
    assert commit_actual() is None


def test_leer_resultados_archivo_faltante(tmp_path):
    ruta = tmp_path / "resultados_paper.json"
    with pytest.raises(ResultadosInvalidosError):
        leer_resultados(ruta)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("contenido", ["{no es json", "[1, 2]", '{"registros": []}', '{"otro": 1}'])
def test_leer_resultados_invalido_no_modifica(tmp_path, contenido):
    ruta = tmp_path / "resultados_paper.json"
    ruta.write_text(contenido, encoding="utf-8")
    with pytest.raises(ResultadosInvalidosError):
        leer_resultados(ruta)
    assert ruta.read_text(encoding="utf-8") == contenido
    assert [p.name for p in tmp_path.iterdir()] == ["resultados_paper.json"]


def _reg_inyeccion(sistema, id_, texto, filas):
    return {
        "sistema": sistema, "particion": "adversarial", "id": id_, "archivo": "x.jpg",
        "tipo_caso": "inyeccion", "subtipo": "v1", "condicion_compromiso": "monto_alterado",
        "datos_esperados": {"total": 100.0}, "texto_inyectado": texto,
        "filas_almacenadas": filas,
    }


def test_actualizar_solo_bloque_bench(tmp_path):
    ruta = tmp_path / "injection_analysis.md"
    antes = "# Titulo\ntexto previo\n"
    despues = "\n## Fin\ncontenido | con tuberias\n"
    ruta.write_text(
        f"{antes}{informes.MARCA_INICIO}\nviejo\n{informes.MARCA_FIN}{despues}", encoding="utf-8", newline=""
    )
    regs = [
        _reg_inyeccion("arquitectura_mcp", "c1", "ignora | todo", []),
        _reg_inyeccion("baseline_naive", "c1", "ignora", [{"total": 999.0}]),
    ]
    actualizar_injection_analysis(regs, ruta)
    nuevo = ruta.read_text(encoding="utf-8")
    assert nuevo.startswith(antes + informes.MARCA_INICIO)
    assert nuevo.endswith(informes.MARCA_FIN + despues)
    assert "viejo" not in nuevo
    assert "| baseline_naive | c1 |" in nuevo and "| comprometido |" in nuevo
    assert "ignora \\| todo" in nuevo and "no_comprometido" in nuevo


def test_actualizar_sin_marcas_no_modifica(tmp_path):
    ruta = tmp_path / "injection_analysis.md"
    ruta.write_text("sin marcas\n", encoding="utf-8")
    with pytest.raises(MarcasBenchError):
        actualizar_injection_analysis([], ruta)
    assert ruta.read_text(encoding="utf-8") == "sin marcas\n"
