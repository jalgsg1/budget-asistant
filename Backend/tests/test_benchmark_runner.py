# -*- coding: utf-8 -*-
"""Pruebas del runner del benchmark (Req. 2.7, 15.2, 15.5 a 15.8, 15.11, 15.12, 15.15).

Sin red ni LLM: todo se hace con dobles.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from hypothesis import given, settings, strategies as st

from agent.hitl import (
    PROMPT_ALERTAS,
    PROMPT_DUPLICADOS,
    PROMPT_MONTO_ALTO,
    PROMPT_REGISTRAR,
    clasificar_prompt,
)
from eval import runner
from eval.golden_set import CasoAdversarial, Original
from eval.runner import (
    SISTEMAS,
    OrdenError,
    PoliticaRespuestasConfirmarTodo,
    ordenar_casos,
    seleccionar,
)
from finanzas_mcp.models import OcrResult
from tests._dobles import FakeClienteLlm, FakeOcr

PBT = settings(max_examples=100, deadline=None)


# ---------------------------------------------------------------------------
# Property 21: Los originales preceden a sus duplicados
# **Validates: Requirements 15.6, 15.7**
# ---------------------------------------------------------------------------

def _original(i: int) -> Original:
    return Original(id=f"orig{i:02d}", ruta=Path(f"orig{i:02d}.png"))


def _caso(i: int, subtipo: str, original_id: str | None) -> CasoAdversarial:
    return CasoAdversarial(
        id=f"caso{i:03d}", archivo=f"adv_{i:03d}.png", ruta=Path(f"adv_{i:03d}.png"),
        tipo="funcional" if subtipo == "factura_duplicada" else "inyeccion",
        subtipo=subtipo, resultado_esperado="x", original_id=original_id,
    )


@st.composite
def _escenarios(draw):
    n_orig = draw(st.integers(0, 4))
    originales = [_original(i) for i in range(n_orig)]
    n = draw(st.integers(1, 12))
    casos = []
    for i in range(n):
        if draw(st.booleans()):
            # El original puede existir o no (referencia colgante).
            ref = draw(st.integers(0, 5))
            casos.append(_caso(i, "factura_duplicada", f"orig{ref:02d}"))
        else:
            casos.append(_caso(i, "inyeccion_directa", None))
    limite = draw(st.one_of(st.none(), st.integers(1, n + 2)))
    return casos, originales, limite


@PBT
@given(_escenarios())
def test_property_21_originales_preceden_duplicados(esc):
    casos, originales, limite = esc
    ids_orig = {o.id for o in originales}
    elegidos = seleccionar([c.archivo for c in casos], limite)
    sel = [c for c in casos if c.archivo in set(elegidos)]
    colgantes = sorted(
        c.id for c in sel if c.subtipo == "factura_duplicada" and c.original_id not in ids_orig
    )
    if colgantes:
        try:
            ordenar_casos(casos, originales, limite)
        except OrdenError as exc:
            assert sorted(exc.ids) == colgantes
        else:
            raise AssertionError("debía fallar con duplicados sin original")
        return

    items = ordenar_casos(casos, originales, limite)
    posicion = {}
    for idx, it in enumerate(items):
        if it.es_original:
            assert it.id not in posicion  # cada original una sola vez
            posicion[it.id] = idx
    for idx, it in enumerate(items):
        if it.subtipo == "factura_duplicada":
            assert posicion[it.original_id] < idx
    # Los casos seleccionados aparecen todos, y los originales van antes de todos ellos.
    no_orig = [i for i, it in enumerate(items) if not it.es_original]
    assert {items[i].id for i in no_orig} == {c.id for c in sel}
    if posicion and no_orig:
        assert max(posicion.values()) < min(no_orig)


def test_orden_error_lista_exactamente_los_id_afectados():
    casos = [
        _caso(1, "factura_duplicada", "orig00"),
        _caso(2, "factura_duplicada", "no_existe"),
        _caso(3, "factura_duplicada", None),
    ]
    try:
        ordenar_casos(casos, [_original(0)], None)
    except OrdenError as exc:
        assert sorted(exc.ids) == ["caso002", "caso003"]
    else:
        raise AssertionError("debía lanzar OrdenError")


def test_original_fuera_del_limite_no_afecta_si_no_hay_duplicados_seleccionados():
    casos = [_caso(1, "inyeccion_directa", None), _caso(2, "factura_duplicada", "no_existe")]
    items = ordenar_casos(casos, [], 1)
    assert [i.id for i in items] == ["caso001"]


# ---------------------------------------------------------------------------
# Property 22: Selección, sistemas y validación de argumentos
# **Validates: Requirements 15.2, 15.11, 15.12, 15.15**
# ---------------------------------------------------------------------------

@PBT
@given(st.lists(st.text(min_size=1, max_size=12), unique=True, max_size=30),
       st.integers(min_value=1, max_value=40))
def test_property_22_seleccionar_primeros_n_alfabeticos(nombres, n):
    res = seleccionar(nombres, n)
    assert res == sorted(nombres)[:n]
    assert len(res) == min(n, len(nombres))
    assert seleccionar(nombres, None) == sorted(nombres)


@PBT
@given(st.one_of(st.integers(max_value=0), st.floats(allow_nan=True), st.text(), st.booleans()))
def test_property_22_seleccionar_rechaza_limites_invalidos(limite):
    if isinstance(limite, int) and not isinstance(limite, bool) and limite >= 1:
        return
    try:
        seleccionar(["a"], limite)
    except ValueError:
        pass
    else:
        raise AssertionError("debía rechazar el límite")


def test_sistemas_son_los_tres_definidos():
    assert SISTEMAS == ("baseline_naive", "baseline_prompt_guarded", "arquitectura_mcp")


@PBT
@given(st.lists(st.text(min_size=1, max_size=6), min_size=1, max_size=4, unique=True))
def test_property_22_un_registro_por_factura_en_baseline(nombres):
    """Un registro por factura procesada, aun si el cliente LLM falla."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        items = []
        for i, n in enumerate(sorted(nombres)):
            p = Path(d) / f"f{i}.png"
            p.write_bytes(b"\x89PNG\r\n")
            items.append(runner.ItemEjecucion(
                id=f"f{i}", archivo=p.name, ruta=str(p), particion="limpia", ground_truth={
                    "imagen": p.name, "comercio": "X", "fecha": "2025-01-01", "moneda": "CRC",
                    "subtotal": 1.0, "iva": 0.0, "total": 1.0, "categoria": "otros",
                    "dificultad": "limpia"}))
        regs = runner.correr_baseline(
            "baseline_naive", "sys", FakeClienteLlm([RuntimeError("falla")]), items, "limpia")
    assert [r.id for r in regs] == [i.id for i in items]
    assert all(r.sistema == "baseline_naive" for r in regs)


try:  # el parser vive en eval/benchmark.py (otra tarea)
    from eval import benchmark as _benchmark
except Exception:  # pragma: no cover
    _benchmark = None


def _validar(argv):
    return _benchmark.validar_argumentos(_benchmark.construir_parser().parse_args(argv))


@PBT
@given(st.integers(min_value=-5, max_value=50),
       st.lists(st.sampled_from(list(SISTEMAS) + ["otro", "x"]), max_size=5))
def test_property_22_validador_de_argumentos(limite, sistemas):
    argv = ["--limite", str(limite)]
    if sistemas:
        argv += ["--sistemas", *sistemas]
    valido = limite >= 1 and all(s in SISTEMAS for s in sistemas)
    try:
        lim, sis, _ = _validar(argv)
    except _benchmark.ErrorCli as exc:
        assert not valido
        msg = str(exc)
        if limite < 1:
            assert "--limite" in msg and ">= 1" in msg
        else:
            assert "--sistemas" in msg and all(s in msg for s in SISTEMAS)
        assert exc.codigo != 0
    else:
        assert valido and lim == limite
        assert set(sis) == (set(sistemas) if sistemas else set(SISTEMAS))


def test_validador_rechaza_limite_no_entero():
    for malo in ("abc", "1.5", ""):
        try:
            _validar(["--limite", malo])
        except _benchmark.ErrorCli as exc:
            assert "--limite" in str(exc)
        else:
            raise AssertionError(f"debía rechazar {malo!r}")


# ---------------------------------------------------------------------------
# Property 27: Conteo de confirmaciones del usuario guionado
# **Validates: Requirements 15.8**
# ---------------------------------------------------------------------------

_CONFIRMACIONES = st.sampled_from([
    f"Ingrese el {PROMPT_REGISTRAR}: ",
    f"Ingrese el {PROMPT_MONTO_ALTO}: ",
    f"{PROMPT_DUPLICADOS} encontrados. ¿Continuar? ",
    f"{PROMPT_ALERTAS}: baja_confianza. Confirme: ",
])
_ACLARACIONES = st.sampled_from([
    "Ingrese el comercio: ", "Categoría (alimentación/transporte): ",
    "El total no coincide con subtotal + iva. Corrija: ", "Fecha (YYYY-MM-DD): ", "",
])


@PBT
@given(st.lists(st.one_of(_CONFIRMACIONES, _ACLARACIONES), max_size=30))
def test_property_27_una_confirmacion_por_prompt_de_confirmacion(prompts):
    io = PoliticaRespuestasConfirmarTodo()
    esperadas = 0
    for p in prompts:
        tipo = clasificar_prompt(p)
        resp = io.ask(p)
        if tipo is None:
            assert resp is None
        else:
            esperadas += 1
            assert resp == io.respuestas_fijas[tipo]
    assert io.confirmaciones == esperadas


# ---------------------------------------------------------------------------
# Ejemplos: politica.json intacto y DB_PATH señuelo intacto (Req. 2.7, 15.5)
# ---------------------------------------------------------------------------

def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _crear_senuelo(ruta: Path) -> None:
    conn = sqlite3.connect(ruta)
    conn.execute("CREATE TABLE senuelo (x TEXT)")
    conn.execute("INSERT INTO senuelo VALUES ('intacto')")
    conn.commit()
    conn.close()


def test_correr_arquitectura_no_toca_politica_ni_db_path(tmp_path, monkeypatch):
    senuelo = tmp_path / "senuelo.db"
    _crear_senuelo(senuelo)
    monkeypatch.setenv("DB_PATH", str(senuelo))
    img = tmp_path / "f.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    hash_pol = _sha(runner.RUTA_POLITICA)
    hash_bd = _sha(senuelo)
    mtime_pol = runner.RUTA_POLITICA.stat().st_mtime_ns

    item = runner.ItemEjecucion(id="f", archivo="f.png", ruta=str(img), particion="adversarial",
                                tipo_caso="inyeccion", subtipo="inyeccion_directa")
    regs = runner.correr_arquitectura(
        [item], "adversarial", FakeOcr(OcrResult(text="", confidence=1.0)))

    assert len(regs) == 1 and regs[0].sistema == "arquitectura_mcp"
    assert _sha(runner.RUTA_POLITICA) == hash_pol
    assert runner.RUTA_POLITICA.stat().st_mtime_ns == mtime_pol
    assert _sha(senuelo) == hash_bd
    conn = sqlite3.connect(senuelo)
    try:
        assert conn.execute("SELECT x FROM senuelo").fetchall() == [("intacto",)]
    finally:
        conn.close()


def test_politica_adaptativa_solo_lee_el_archivo():
    antes = _sha(runner.RUTA_POLITICA)
    policy, raw = runner.politica_adaptativa()
    assert policy.modo_hitl == "adaptativo" and raw["modo_hitl"] == "adaptativo"
    assert _sha(runner.RUTA_POLITICA) == antes
