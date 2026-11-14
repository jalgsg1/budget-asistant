# -*- coding: utf-8 -*-
"""Propiedades 19 y 20: validadores del Golden Set (Req. 12.x, 13.x, 14.x). Sin red ni LLM."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

from eval.convertir_labels import convertir_filas
from eval.golden_set import (
    CONDICIONES_COMPROMISO,
    validar_ground_truth,
    validar_manifiesto,
    validar_particion_limpia,
)
from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST

SETTINGS = settings(max_examples=100, deadline=None)

# ----------------------------------------------------------------- Property 19

DIFS = ["limpia", "borrosa", "inclinada", "multiples_descuentos", "duplicada"]


def _entrada(nombre, cat="x"):
    return {
        "imagen": nombre, "comercio": "Super Central", "fecha": "2024-02-29", "moneda": "CRC",
        "subtotal": "100.00", "iva": 13, "total": 113.0,
        "categoria": sorted(CLOSED_CATEGORY_LIST)[0], "dificultad": "limpia",
    }


# (campo, valor inválido)
INVALIDOS = [
    ("fecha", "2023-02-29"), ("fecha", "2024-13-01"), ("fecha", "15/01/2024"),
    ("moneda", "crc"), ("moneda", "CR"), ("moneda", "CRCC"),
    ("total", -1.0), ("subtotal", "10.123"), ("iva", "-0.01"), ("total", "abc"),
    ("categoria", "NoExiste"), ("dificultad", "otra"),
    ("comercio", "x" * 101), ("comercio", ""),
]
CAMPOS_OBLIG = ["comercio", "fecha", "moneda", "subtotal", "iva", "total", "categoria", "dificultad"]


@st.composite
def escenario_gt(draw):
    n = draw(st.integers(0, 8))
    nombres = [f"f{i}.jpg" for i in range(n)]
    entradas = [_entrada(nm) for nm in nombres]
    invalidos = {}
    for i in draw(st.sets(st.integers(0, max(n - 1, 0)), max_size=n) if n else st.just(set())):
        kind = draw(st.sampled_from(["inv", "falta"]))
        if kind == "inv":
            campo, val = draw(st.sampled_from(INVALIDOS))
            entradas[i][campo] = val
            invalidos[nombres[i]] = campo
        else:
            campo = draw(st.sampled_from(CAMPOS_OBLIG))
            del entradas[i][campo]
            invalidos[nombres[i]] = campo
    imagenes = set(nombres)
    sin_entrada = set()
    for i in draw(st.sets(st.integers(0, max(n - 1, 0)), max_size=n) if n else st.just(set())):
        imagenes.discard(nombres[i])
        sin_entrada.add(nombres[i])  # entrada sin imagen
    extra = {f"extra{i}.png" for i in range(draw(st.integers(0, 3)))}  # imagen sin entrada
    imagenes |= extra
    dups = set()
    for i in draw(st.sets(st.integers(0, max(n - 1, 0)), max_size=n) if n else st.just(set())):
        entradas.append(copy.deepcopy(entradas[i]))
        dups.add(nombres[i])
    return entradas, imagenes, invalidos, sin_entrada, extra, dups


class TestProperty19(unittest.TestCase):
    """**Validates: Requirements 12.3, 12.4, 12.8, 12.9, 12.10**"""

    @SETTINGS
    @given(escenario_gt())
    def test_reporta_exactamente_los_ofensivos(self, esc):
        entradas, imagenes, invalidos, sin_imagen, extra, dups = esc
        snapshot = copy.deepcopy(entradas)
        errores = validar_ground_truth(entradas, imagenes)
        self.assertEqual(entradas, snapshot)  # no muta la entrada

        def por(sub):
            return {e.nombre for e in errores if sub in e.motivo}

        self.assertEqual(por("no tiene entrada"), extra)
        self.assertEqual(por("imagen inexistente"), sin_imagen)
        self.assertEqual(por("entradas (debe"), dups)
        # los campos inválidos o ausentes se reportan para cada entrada ofensiva
        for nombre, campo in invalidos.items():
            self.assertTrue(
                any(e.nombre == nombre and campo in e.motivo for e in errores),
                f"{nombre}/{campo} no reportado: {errores}")
        limpios = set(errores_n.nombre for errores_n in errores)
        todos = {e["imagen"] for e in entradas}
        esperados = set(invalidos) | extra | dups | sin_imagen
        self.assertEqual(limpios, esperados)
        if not esperados:
            self.assertEqual(errores, [])
        self.assertTrue(todos >= set(invalidos))

    def test_particion_limpia_no_modifica_archivos(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "images").mkdir()
            (base / "images" / "a.jpg").write_bytes(b"jpg")
            (base / "ground_truth.json").write_text(json.dumps([_entrada("a.jpg")]), encoding="utf-8")
            (base / "anotaciones_anotador_1.json").write_text("[]", encoding="utf-8")

            def estado():
                return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in base.rglob("*") if p.is_file()}

            antes = estado()
            errores = validar_particion_limpia(base)
            self.assertTrue(errores)  # conteos y anotador 2 faltante
            self.assertEqual(estado(), antes)
            self.assertEqual(sorted(p.name for p in base.rglob("*")),
                             sorted(["images", "a.jpg", "ground_truth.json", "anotaciones_anotador_1.json"]))

    @SETTINGS
    @given(st.lists(st.fixed_dictionaries({
        "imagen": st.text(max_size=8), "comercio": st.text(max_size=8), "fecha": st.text(max_size=10),
        "total": st.text(max_size=6), "moneda": st.text(max_size=4), "categoria": st.text(max_size=6),
        "dificultad": st.sampled_from(["", "clean", "blurry", "tilted", "discount", "duplicate", "injection"]),
    }), max_size=20))
    def test_conversion_una_entrada_por_fila(self, filas):
        copia = copy.deepcopy(filas)
        salida = convertir_filas(filas)
        self.assertEqual(len(salida), len(filas))
        self.assertEqual(filas, copia)


# ----------------------------------------------------------------- Property 20

MUTACIONES_INT = ["falta_campo", "archivo_inexistente", "archivo_vacio", "resultado_malo"]
MUTACIONES_INY = MUTACIONES_INT + ["sin_vector", "sin_texto", "condicion_mala"]


def _caso(i, tipo):
    base = {"id": f"c{i}", "archivo": f"c{i}.jpg", "tipo": tipo}
    if tipo == "integridad":
        base.update(subtipo="inconsistencia_aritmetica", resultado_esperado="no_registrar")
    else:
        base.update(subtipo="inyeccion_directa", resultado_esperado="no_comprometer", vector="v1",
                    texto_inyectado="ignora las reglas", condicion_compromiso=CONDICIONES_COMPROMISO[0],
                    datos_esperados={"total": "10.00"})
    return base


@st.composite
def escenario_manifiesto(draw):
    n = draw(st.integers(0, 8))
    casos, ofensivos = [], set()
    for i in range(n):
        tipo = draw(st.sampled_from(["integridad", "inyeccion"]))
        c = _caso(i, tipo)
        mut = draw(st.sampled_from([None] + (MUTACIONES_INT if tipo == "integridad" else MUTACIONES_INY)))
        existe, vacio = True, False
        if mut == "falta_campo":
            del c[draw(st.sampled_from(["archivo", "subtipo", "resultado_esperado"]))]
        elif mut == "archivo_inexistente":
            existe = False
        elif mut == "archivo_vacio":
            vacio = True
        elif mut == "resultado_malo":
            c["resultado_esperado"] = "otro"
        elif mut == "sin_vector":
            c["vector"] = draw(st.sampled_from(["", "  "]))
        elif mut == "sin_texto":
            del c["texto_inyectado"]
        elif mut == "condicion_mala":
            c["condicion_compromiso"] = "nada"
        if mut:
            ofensivos.add(c["id"])
        casos.append((c, existe, vacio))
    repetidos = set()
    if n:
        for i in draw(st.sets(st.integers(0, n - 1), max_size=2)):
            dup = copy.deepcopy(casos[i][0])
            casos.append((dup, True, False))
            repetidos.add(dup["id"])
    return casos, ofensivos | repetidos


class TestProperty20(unittest.TestCase):
    """**Validates: Requirements 13.1, 13.6, 13.7, 13.8, 14.4, 14.6, 14.8**"""

    @SETTINGS
    @given(escenario_manifiesto())
    def test_reporta_exactamente_los_casos_ofensivos(self, esc):
        casos, ofensivos = esc
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for c, existe, vacio in casos:
                if existe and c.get("archivo"):
                    (base / c["archivo"]).write_bytes(b"" if vacio else b"img")
            manifiesto = {"originales": [], "casos": [c for c, _, _ in casos]}
            ruta = base / "adversarial_manifest.json"
            ruta.write_text(json.dumps(manifiesto), encoding="utf-8")
            antes = (ruta.read_bytes(), ruta.stat().st_mtime_ns)
            archivos_antes = sorted(p.name for p in base.iterdir())

            copia = copy.deepcopy(manifiesto)
            errores = validar_manifiesto(manifiesto, base)

            self.assertEqual(manifiesto, copia)
            self.assertEqual((ruta.read_bytes(), ruta.stat().st_mtime_ns), antes)
            self.assertEqual(sorted(p.name for p in base.iterdir()), archivos_antes)
            ids = {c["id"] for c, _, _ in casos if "id" in c}
            reportados = {e.nombre for e in errores if e.nombre in ids}
            self.assertEqual(reportados, ofensivos)

    def test_manifiesto_sin_lista_de_casos(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(validar_manifiesto({}, Path(tmp))), 1)


if __name__ == "__main__":
    unittest.main()
