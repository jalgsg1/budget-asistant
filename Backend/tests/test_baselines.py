# -*- coding: utf-8 -*-
"""Pruebas de los baselines (Req. 9.4, 9.9, 10.10, 11.2, 19.9).

Propiedades 15, 16 y 17 del diseño, más pruebas de ejemplo por baseline.
Sin red: se usa ``FakeClienteLlm`` y ``SinRedTestCase``.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from baseline import _comun, baseline_naive, baseline_prompt_guarded
from baseline._comun import ProcesadorBaseline, correr, main_baseline
from baseline.bd_temporal import BDTemporal
from baseline.llm import ConfigLlmError, RespuestaLlm, resolver_config_llm
from baseline.traza_comun import TrazaComun
from tests._dobles import FakeClienteLlm, RelojFalso
from tests._sin_red import SinRedTestCase

RAIZ = Path(__file__).resolve().parent.parent
AJUSTES = dict(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


def _args(i: int = 0, moneda: str = "CRC") -> dict:
    return {
        "comercio": f"Comercio{i}", "fecha": "2024-01-15", "total": 113.0,
        "moneda": moneda, "categoria": "alimentos", "subtotal": 100.0, "iva": 13.0,
        "descripcion": "x",
    }


def _llamada(i: int = 0, moneda: str = "CRC") -> list[dict]:
    return [{"nombre": "insertar_transaccion", "args": _args(i, moneda)}]


class _BaseBaselines(SinRedTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="test_baselines_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.contador = 0

    def facturas(self, n: int) -> list[str]:
        self.contador += 1
        base = Path(self.tmp) / f"lote{self.contador}"
        base.mkdir()
        rutas = []
        for i in range(n):
            p = base / f"f{i}.png"
            p.write_bytes(b"\x89PNG-fake")
            rutas.append(str(p))
        return rutas

    def dir_trazas(self) -> str:
        self.contador += 1
        return str(Path(self.tmp) / f"trazas{self.contador}")

    @contextlib.contextmanager
    def espiar_bd(self):
        """Registra cada ``BDTemporal`` creada por ``correr``."""
        creadas: list[BDTemporal] = []

        class Espia(BDTemporal):
            def __enter__(self_inner):
                r = super().__enter__()
                creadas.append(self_inner)
                return r

        with mock.patch("baseline._comun.BDTemporal", Espia):
            yield creadas


# ---------------------------------------------------------------------------
# Property 15
# ---------------------------------------------------------------------------
class TestPropiedad15CicloDeVidaBD(_BaseBaselines):
    """**Validates: Requirements 10.5, 11.1, 11.3, 15.4, 15.10**"""

    @settings(**AJUSTES)
    @given(
        desenlaces=st.lists(st.sampled_from(["ok", "error_llm", "error_bd"]), min_size=0, max_size=4),
        interrupcion=st.booleans(),
        conservar=st.booleans(),
    )
    def test_property_15_ciclo_de_vida_bd_temporal(self, desenlaces, interrupcion, conservar):
        guion: list = []
        for i, d in enumerate(desenlaces):
            guion.append({"ok": _llamada(i), "error_llm": RuntimeError("boom"),
                          "error_bd": _llamada(i, "EUR")}[d])
        if interrupcion:
            guion.append(KeyboardInterrupt())
        if not guion:
            guion = [[]]
        rutas = self.facturas(max(len(guion), 1) if desenlaces or interrupcion else 0)
        db_path = Path(self.tmp) / "principal.db"
        db_path.write_bytes(b"contenido-intacto")

        with mock.patch.dict(os.environ, {"DB_PATH": str(db_path)}), \
                contextlib.redirect_stderr(io.StringIO()), self.espiar_bd() as creadas:
            try:
                corrida = correr("baseline_naive", "p", FakeClienteLlm(guion), rutas, None, conservar)
            except KeyboardInterrupt:
                corrida = None
        self.assertEqual(len(creadas), 1)
        bd = creadas[0]
        directorio = Path(bd.ruta).parent
        try:
            if conservar and corrida is not None:
                self.assertEqual(corrida.ruta_bd, bd.ruta)
                self.assertTrue(os.path.exists(bd.ruta))
            elif conservar:
                # Interrupción: se pidió conservar, el archivo permanece.
                self.assertTrue(os.path.exists(bd.ruta))
            else:
                self.assertFalse(os.path.exists(bd.ruta))
                self.assertFalse(directorio.exists())
                if corrida is not None:
                    self.assertIsNone(corrida.ruta_bd)
            self.assertEqual(db_path.read_bytes(), b"contenido-intacto")
        finally:
            shutil.rmtree(directorio, ignore_errors=True)

    @settings(**AJUSTES)
    @given(st.integers(min_value=2, max_value=3))
    def test_property_15_bd_inicia_vacia_y_es_distinta(self, n):
        rutas = []
        for _ in range(n):
            with BDTemporal() as bd:
                self.assertEqual(bd.contar(), 0)
                self.assertTrue(os.path.exists(bd.ruta))
                rutas.append(bd.ruta)
                with BDTemporal() as otra:
                    self.assertNotEqual(bd.ruta, otra.ruta)
        self.assertEqual(len(set(rutas)), n)
        for r in rutas:
            self.assertFalse(os.path.exists(r))
            self.assertFalse(os.path.exists(os.path.dirname(r)))


# ---------------------------------------------------------------------------
# Property 16
# ---------------------------------------------------------------------------
class TestPropiedad16AislamientoDeErrores(_BaseBaselines):
    """**Validates: Requirements 9.7, 9.8, 10.7, 10.8, 10.9, 15.9**"""

    @settings(**AJUSTES)
    @given(
        desenlaces=st.lists(st.sampled_from(["ok", "error_llm", "error_bd", "sin_llamada"]),
                            min_size=1, max_size=6),
        nombre=st.sampled_from(["baseline_naive", "baseline_prompt_guarded"]),
    )
    def test_property_16_una_traza_por_factura_y_errores_aislados(self, desenlaces, nombre):
        guion = []
        for i, d in enumerate(desenlaces):
            guion.append({"ok": _llamada(i), "error_llm": ValueError("x"),
                          "error_bd": _llamada(i, "EUR"), "sin_llamada": []}[d])
        rutas = self.facturas(len(desenlaces))
        trazas = self.dir_trazas()
        with contextlib.redirect_stderr(io.StringIO()), self.espiar_bd() as creadas:
            # Se inspeccionan las filas antes de que se borre la BD.
            filas_finales: list[dict] = []
            original = ProcesadorBaseline.procesar

            def procesar(self_p, ruta):
                r = original(self_p, ruta)
                filas_finales[:] = self_p.bd.filas()
                return r

            with mock.patch.object(ProcesadorBaseline, "procesar", procesar):
                corrida = correr(nombre, "p", FakeClienteLlm(guion), rutas, trazas)

        self.assertEqual(len(corrida.resultados), len(desenlaces))
        archivos = sorted(Path(trazas).glob("traza_*.json"))
        self.assertEqual(len(archivos), len(desenlaces))
        esperados_ok = []
        for i, (d, r) in enumerate(zip(desenlaces, corrida.resultados)):
            self.assertEqual(r.traza.ruta_factura, rutas[i])
            if d == "ok":
                self.assertEqual(r.traza.estado_final, "registrada")
                self.assertTrue(r.traza.registro_en_bd)
                esperados_ok.append(f"Comercio{i}")
            elif d == "sin_llamada":
                self.assertEqual(r.traza.estado_final, "rechazada")
                self.assertFalse(r.traza.registro_en_bd)
            else:
                self.assertEqual(r.traza.estado_final, "error")
                self.assertFalse(r.traza.registro_en_bd)
                self.assertEqual(r.filas_nuevas, [])
                self.assertIsNotNone(r.indicacion_error)
        # Las filas de facturas correctas permanecen y las fallidas no dejan nada.
        self.assertEqual([f["comercio"] for f in filas_finales], esperados_ok)
        self.assertEqual(len(creadas), 1)


# ---------------------------------------------------------------------------
# Property 17
# ---------------------------------------------------------------------------
class TestPropiedad17EntornoObligatorio(_BaseBaselines):
    """**Validates: Requirements 9.10, 15.13**"""

    @settings(**AJUSTES)
    @given(
        proveedor=st.sampled_from(["openai", "anthropic"]),
        tiene_proveedor=st.booleans(),
        tiene_modelo=st.booleans(),
        tiene_clave=st.booleans(),
    )
    def test_property_17_variables_faltantes_se_nombran_y_no_se_crea_nada(
        self, proveedor, tiene_proveedor, tiene_modelo, tiene_clave
    ):
        clave_var = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[proveedor]
        env: dict[str, str] = {}
        if tiene_proveedor:
            env["LLM_PROVIDER"] = proveedor
        if tiene_modelo:
            env["OCR_MODEL"] = "modelo-x"
        if tiene_clave:
            env[clave_var] = "k"
        faltantes = []
        if not tiene_proveedor:
            faltantes.append("LLM_PROVIDER")
        if not tiene_modelo:
            faltantes.append("OCR_MODEL")
        if tiene_proveedor and not tiene_clave:
            faltantes.append(clave_var)

        if not faltantes:
            cfg = resolver_config_llm(env)
            self.assertEqual(cfg.proveedor, proveedor)
            return

        with self.assertRaises(ConfigLlmError) as cm:
            resolver_config_llm(env)
        for v in faltantes:
            self.assertIn(v, str(cm.exception))

        trazas = self.dir_trazas()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("baseline._comun.BDTemporal") as bd_mock, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            codigo = main_baseline("baseline_naive", "p", [self.facturas(1)[0], "--trazas", trazas])
        self.assertNotEqual(codigo, 0)
        bd_mock.assert_not_called()
        self.assertFalse(os.path.exists(trazas))
        for v in faltantes:
            self.assertIn(v, err.getvalue())


# ---------------------------------------------------------------------------
# Pruebas de ejemplo por baseline
# ---------------------------------------------------------------------------
class _EjemplosBaseline:
    modulo = None

    def test_bd_existe_durante_la_corrida_y_se_borra_despues(self):
        rutas = self.facturas(1)
        visto = {}

        class Cliente(FakeClienteLlm):
            def invocar(s, *a, **k):
                visto["ruta"] = creadas[0].ruta
                visto["existe"] = os.path.exists(creadas[0].ruta)
                return super().invocar(*a, **k)

        with self.espiar_bd() as creadas:
            corrida = correr(self.modulo.NOMBRE, self.prompt, Cliente([_llamada(0)]), rutas, None)
        self.assertTrue(visto["existe"])
        self.assertFalse(os.path.exists(visto["ruta"]))
        self.assertEqual(corrida.resultados[0].traza.estado_final, "registrada")

    def test_bd_se_borra_incluso_con_error(self):
        rutas = self.facturas(2)
        with contextlib.redirect_stderr(io.StringIO()), self.espiar_bd() as creadas:
            corrida = correr(self.modulo.NOMBRE, self.prompt,
                             FakeClienteLlm([RuntimeError("x")]), rutas, None)
        self.assertEqual([r.traza.estado_final for r in corrida.resultados], ["error", "error"])
        self.assertFalse(os.path.exists(creadas[0].ruta))

    def test_bd_se_borra_ante_excepcion_no_controlada(self):
        rutas = self.facturas(1)
        with self.espiar_bd() as creadas:
            with self.assertRaises(KeyboardInterrupt):
                correr(self.modulo.NOMBRE, self.prompt, FakeClienteLlm([KeyboardInterrupt()]), rutas, None)
        self.assertFalse(os.path.exists(creadas[0].ruta))

    def test_se_genera_la_traza(self):
        rutas = self.facturas(1)
        trazas = self.dir_trazas()
        correr(self.modulo.NOMBRE, self.prompt, FakeClienteLlm([_llamada(0)]), rutas, trazas)
        archivos = list(Path(trazas).glob("traza_*.json"))
        self.assertEqual(len(archivos), 1)
        traza = TrazaComun.desde_dict(json.loads(archivos[0].read_text(encoding="utf-8")))
        self.assertEqual(traza.sistema, self.modulo.NOMBRE)
        self.assertEqual(traza.ruta_factura, rutas[0])
        self.assertEqual((traza.tokens_entrada, traza.tokens_salida), (10, 5))
        self.assertTrue(traza.registro_en_bd)

    def test_se_pasa_prompt_y_herramienta_al_cliente(self):
        cliente = FakeClienteLlm([[]])
        correr(self.modulo.NOMBRE, self.prompt, cliente, self.facturas(1), None)
        self.assertEqual(cliente.llamadas[0]["system_prompt"], self.prompt)
        self.assertEqual(cliente.llamadas[0]["herramienta"]["name"], "insertar_transaccion")
        self.assertEqual(cliente.llamadas[0]["mime"], "image/png")

    def test_duracion_con_reloj_inyectado(self):
        reloj = RelojFalso()
        cliente = FakeClienteLlm([("bloquear", 12.5, [])], reloj=reloj)
        with BDTemporal() as bd:
            proc = ProcesadorBaseline(self.modulo.NOMBRE, self.prompt, cliente, bd, None, reloj=reloj)
            r = proc.procesar(self.facturas(1)[0])
        self.assertEqual(r.traza.duracion_ms, 12500.0)
        self.assertEqual(r.traza.estado_final, "rechazada")

    def test_timeout_marca_error_y_no_deja_filas(self):
        liberar = threading.Event()

        class Bloqueado:
            def invocar(s, *a, **k):
                liberar.wait(10)
                return RespuestaLlm([], 0, 0)

        reloj = RelojFalso()
        try:
            with contextlib.redirect_stderr(io.StringIO()), BDTemporal() as bd:
                proc = ProcesadorBaseline(self.modulo.NOMBRE, self.prompt, Bloqueado(), bd, None,
                                          timeout_s=0.05, reloj=reloj)
                r = proc.procesar(self.facturas(1)[0])
                self.assertEqual(bd.contar(), 0)
        finally:
            liberar.set()
        self.assertEqual(r.indicacion_error, "timeout")
        self.assertEqual(r.traza.estado_final, "error")
        self.assertFalse(r.traza.registro_en_bd)


class TestBaselineNaive(_EjemplosBaseline, _BaseBaselines):
    modulo = baseline_naive
    prompt = baseline_naive.SYSTEM_PROMPT_NAIVE


class TestBaselinePromptGuarded(_EjemplosBaseline, _BaseBaselines):
    modulo = baseline_prompt_guarded
    prompt = baseline_prompt_guarded.SYSTEM_PROMPT_GUARDED

    def test_prompt_guarded_incluye_defensas(self):
        for fragmento in ("DATOS", "R2", "R3", "R5"):
            self.assertIn(fragmento, self.prompt)
        self.assertNotEqual(self.prompt, baseline_naive.SYSTEM_PROMPT_NAIVE)


# ---------------------------------------------------------------------------
# Análisis AST de imports prohibidos
# ---------------------------------------------------------------------------
class TestImportsProhibidos(unittest.TestCase):
    """Los baselines no dependen de ocr_mcp ni de finanzas_mcp (Req. 9.4, 10.10, 11.2, 19.9)."""

    PROHIBIDOS = ("ocr_mcp", "finanzas_mcp")

    @staticmethod
    def _modulos_importados(ruta: Path) -> list[str]:
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        modulos: list[str] = []
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos += [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
                modulos.append(nodo.module)
        return modulos

    def test_ningun_modulo_de_baseline_importa_codigo_del_sistema(self):
        archivos = sorted((RAIZ / "baseline").glob("*.py"))
        self.assertTrue(archivos)
        for ruta in archivos:
            for mod in self._modulos_importados(ruta):
                for prohibido in self.PROHIBIDOS:
                    self.assertFalse(
                        mod == prohibido or mod.startswith(prohibido + "."),
                        f"{ruta.name} importa {mod}",
                    )

    def test_bd_temporal_solo_lee_el_esquema_como_texto(self):
        fuente = (RAIZ / "baseline" / "bd_temporal.py").read_text(encoding="utf-8")
        self.assertIn("schema.sql", fuente)
        self.assertFalse(any(m.startswith("finanzas_mcp")
                             for m in self._modulos_importados(RAIZ / "baseline" / "bd_temporal.py")))


if __name__ == "__main__":
    unittest.main()
