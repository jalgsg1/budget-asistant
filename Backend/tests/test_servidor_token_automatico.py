# -*- coding: utf-8 -*-
"""Propiedades del servidor ante el Token_Automatico (tarea 7.3).

Property 9:  El servidor rechaza todo Token_Automatico en modo siempre.
             **Validates: Requirements 3.2, 3.3**
Property 10: Revalidación independiente y prioridad de códigos con Token_Automatico.
             **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8**
Property 11: El servidor ignora los parámetros HITL del payload.
             **Validates: Requirements 6.7**
Property 12: Las reglas de negocio no dependen del modo con token de usuario.
             **Validates: Requirements 5.9**
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import tempfile
import unittest
from datetime import date, timedelta

from hypothesis import given, settings, strategies as st

from tests._sin_red import SinRedTestCase

_TMP = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_TMP, "token_auto.db"))

from mcp import types  # noqa: E402

from finanzas_mcp import server  # noqa: E402
from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST  # noqa: E402
from finanzas_mcp.business.hitl import es_token_automatico  # noqa: E402
from finanzas_mcp.business.transacciones import (  # noqa: E402
    ValidationError,
    registrar_transaccion,
)
from finanzas_mcp.db.repository import TransactionRepository  # noqa: E402
from finanzas_mcp.models import Transaction  # noqa: E402

USER = "usuario-prueba"
UMBRAL_OCR = 0.75
UMBRALES = {"CRC": 50000, "USD": 100}
AYER = (date.today() - timedelta(days=1)).isoformat()


def _politica(modo: str | None) -> dict:
    pol = {
        "high_amount_threshold": dict(UMBRALES),
        "umbral_confianza_ocr": UMBRAL_OCR,
        "max_date_range_days": 90,
        "allowed_filters": ["comercio", "fecha_desde", "fecha_hasta", "categoria", "moneda"],
    }
    if modo is not None:
        pol["modo_hitl"] = modo
    return pol


# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------

_comercios = st.sampled_from(["Super Test", "Tienda X", ""])
_fechas = st.sampled_from([AYER, AYER, AYER, "2999-01-01", "no-es-fecha"])
_monedas = st.sampled_from(["USD", "USD", "CRC", "CRC", "EUR"])
_categorias = st.sampled_from(list(CLOSED_CATEGORY_LIST) + ["Inventada"])
_totales = st.one_of(
    st.floats(min_value=0.01, max_value=300.0, allow_nan=False).map(lambda x: round(x, 2)),
    st.floats(min_value=0.01, max_value=120000.0, allow_nan=False).map(lambda x: round(x, 2)),
)
_aritmetica = st.sampled_from(["ninguna", "consistente", "inconsistente"])
_confianzas = st.one_of(
    st.none(),
    st.just(UMBRAL_OCR),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
_sospechoso = st.sampled_from([None, True, False])
_hat = st.sampled_from([None, "tok-alto"])


@st.composite
def _datos(draw, validos: bool = False):
    if validos:
        total = draw(st.floats(min_value=0.01, max_value=99.0).map(lambda x: round(x, 2)))
        d = {
            "comercio": "Super Test",
            "fecha": AYER,
            "total": total,
            "moneda": draw(st.sampled_from(["USD", "CRC"])),
            "categoria": draw(st.sampled_from(list(CLOSED_CATEGORY_LIST))),
        }
    else:
        d = {
            "comercio": draw(_comercios),
            "fecha": draw(_fechas),
            "total": draw(_totales),
            "moneda": draw(_monedas),
            "categoria": draw(_categorias),
        }
    modo = draw(_aritmetica)
    if modo == "consistente":
        sub = round(d["total"] / 2, 2)
        d["subtotal"], d["iva"] = sub, round(d["total"] - sub, 2)
    elif modo == "inconsistente":
        d["subtotal"], d["iva"] = round(d["total"] + 5.0, 2), 1.0
    return d


def _aritmetica_invalida(d: dict) -> bool:
    if d.get("subtotal") is None or d.get("iva") is None:
        return False
    return round(abs(d["subtotal"] + d["iva"] - d["total"]), 2) > 0.01


def _contar(repo: TransactionRepository) -> int:
    return repo._conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def _sembrar_duplicado(repo: TransactionRepository, d: dict) -> None:
    repo.insert(
        Transaction(
            user_id=USER, comercio=d["comercio"] or "Super Test", fecha=AYER if not d["fecha"] else d["fecha"],
            total=float(d["total"]), moneda="USD", categoria=CLOSED_CATEGORY_LIST[0],
        )
    )


def _ejecutar(datos, token, hat, modo, duplicado=False, conf=None, cont=None):
    """Corre registrar_transaccion en un repositorio temporal nuevo.

    Devuelve (código de error o None, filas nuevas, mensaje).
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = TransactionRepository(os.path.join(tmp, "t.db"))
        try:
            if duplicado:
                _sembrar_duplicado(repo, datos)
            antes = _contar(repo)
            try:
                registrar_transaccion(
                    repo, dict(datos), token, hat, _politica(modo), USER,
                    confianza_ocr=conf, contenido_sospechoso=cont,
                )
                codigo, msg = None, ""
            except ValidationError as exc:
                codigo, msg = exc.result.error_code, str(exc)
            return codigo, _contar(repo) - antes, msg
        finally:
            repo.close()


def _codigo_base(d: dict):
    """Código de R1, R2, R3 o R6 (en ese orden) o None."""
    if not d["comercio"]:
        return "MISSING_FIELDS"
    if d["fecha"] == "no-es-fecha":
        return "INVALID_DATE_FORMAT"
    if d["fecha"] == "2999-01-01":
        return "FUTURE_DATE"
    if d["moneda"] not in UMBRALES:
        return "INVALID_CURRENCY"
    if d["categoria"] not in CLOSED_CATEGORY_LIST:
        return "INVALID_CATEGORY"
    return None


# ---------------------------------------------------------------------------
# Property 9
# ---------------------------------------------------------------------------

class TestProperty9AutoRechazadoEnSiempre(SinRedTestCase):
    @settings(max_examples=60, deadline=None)
    @given(
        d=_datos(),
        sufijo=st.text(max_size=20),
        espacios=st.sampled_from(["", " ", "  "]),
        modo=st.sampled_from(["siempre", None]),
        hat=_hat,
        conf=_confianzas,
        cont=_sospechoso,
    )
    def test_auto_en_siempre_rechazado_sin_filas(self, d, sufijo, espacios, modo, hat, conf, cont):
        token = f"{espacios}auto:{sufijo}"
        self.assertTrue(es_token_automatico(token))
        codigo, nuevas, _ = _ejecutar(d, token, hat, modo, conf=conf, cont=cont)
        self.assertEqual(codigo, "AUTOMATIC_TOKEN_NOT_ALLOWED")
        self.assertEqual(nuevas, 0)

    @settings(max_examples=40, deadline=None)
    @given(
        d=_datos(validos=True),
        token=st.sampled_from([None, "", "   ", "\t"]),
        modo=st.sampled_from(["siempre", "adaptativo", None]),
    )
    def test_sin_token_falla_con_missing_confirmation(self, d, token, modo):
        codigo, nuevas, _ = _ejecutar(d, token, None, modo)
        # R1-R7 pasan con datos válidos de monto bajo; R8 exige el token.
        if d.get("subtotal") is not None and _aritmetica_invalida(d):
            self.assertEqual(codigo, "ARITHMETIC_INCONSISTENCY")
        else:
            self.assertEqual(codigo, "MISSING_CONFIRMATION_TOKEN")
        self.assertEqual(nuevas, 0)


# ---------------------------------------------------------------------------
# Property 10
# ---------------------------------------------------------------------------

class TestProperty10RevalidacionIndependiente(SinRedTestCase):
    @settings(max_examples=150, deadline=None)
    @given(
        d=_datos(),
        hat=_hat,
        conf=_confianzas,
        cont=_sospechoso,
        duplicado=st.booleans(),
    )
    def test_prioridad_de_codigos(self, d, hat, conf, cont, duplicado):
        codigo, nuevas, msg = _ejecutar(
            d, "auto:" + "a" * 8, hat, "adaptativo", duplicado=duplicado, conf=conf, cont=cont
        )

        esperado = _codigo_base(d)
        if esperado is None:
            if d["total"] > UMBRALES[d["moneda"]]:
                esperado = "HIGH_AMOUNT_CONFIRMATION_REQUIRED"
            elif (
                _aritmetica_invalida(d)
                or duplicado
                or conf is None
                or conf < UMBRAL_OCR
                or cont is not False
            ):
                esperado = "HUMAN_CONFIRMATION_REQUIRED"

        self.assertEqual(codigo, esperado)
        self.assertEqual(nuevas, 1 if esperado is None else 0)
        if codigo == "HUMAN_CONFIRMATION_REQUIRED":
            bajo = msg.lower()
            for palabra in ("duplic", "aritm", "arithmetic", "confianza", "sospech", "contenido", "ocr"):
                self.assertNotIn(palabra, bajo)


# ---------------------------------------------------------------------------
# Property 11 (vía el handler del servidor MCP)
# ---------------------------------------------------------------------------

class TestProperty11IgnoraParametrosHitlDelPayload(SinRedTestCase):
    def setUp(self) -> None:
        # El loop de asyncio en Windows abre un socketpair; crearlo antes del bloqueo.
        self._loop = asyncio.new_event_loop()
        self.addCleanup(self._loop.close)
        super().setUp()
        self._repo_orig, self._pol_orig = server._repo, server._policy
        self.addCleanup(self._restaurar)

    def _restaurar(self) -> None:
        server._repo, server._policy = self._repo_orig, self._pol_orig

    def _llamar(self, args: dict, modo: str, duplicado: bool):
        handler = server.server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="registrar_transaccion", arguments=args),
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = TransactionRepository(os.path.join(tmp, "t.db"))
            try:
                server._repo, server._policy = repo, _politica(modo)
                if duplicado:
                    _sembrar_duplicado(repo, args)
                antes = _contar(repo)
                with contextlib.redirect_stdout(io.StringIO()):
                    res = self._loop.run_until_complete(handler(req)).root
                return bool(res.isError), res.content[0].text, _contar(repo) - antes
            finally:
                server._repo = self._repo_orig
                repo.close()

    @settings(max_examples=60, deadline=None)
    @given(
        d=_datos(),
        modo=st.sampled_from(["siempre", "adaptativo"]),
        token=st.sampled_from(["auto:abc", "confirmo-usuario"]),
        hat=_hat,
        conf=_confianzas,
        cont=_sospechoso,
        duplicado=st.booleans(),
        modo_payload=st.sampled_from(["siempre", "adaptativo", "otro", None, 7]),
        umbral_payload=st.one_of(
            st.none(), st.floats(min_value=-1.0, max_value=2.0, allow_nan=False), st.text(max_size=5)
        ),
    )
    def test_resultado_identico_con_o_sin_campos_hitl(
        self, d, modo, token, hat, conf, cont, duplicado, modo_payload, umbral_payload
    ):
        base = dict(d, confirmation_token=token)
        if hat:
            base["high_amount_token"] = hat
        if conf is not None:
            base["confianza_ocr"] = conf
        if cont is not None:
            base["contenido_sospechoso"] = cont
        con_extra = dict(base, modo_hitl=modo_payload, umbral_confianza_ocr=umbral_payload)

        sin = self._llamar(base, modo, duplicado)
        con = self._llamar(con_extra, modo, duplicado)
        self.assertEqual(sin, con)


# ---------------------------------------------------------------------------
# Property 12
# ---------------------------------------------------------------------------

_tokens_usuario = st.one_of(
    st.none(),
    st.text(max_size=15).filter(lambda t: not es_token_automatico(t)),
    st.sampled_from(["confirmo", "si", "", "  "]),
)


class TestProperty12ReglasIndependientesDelModo(SinRedTestCase):
    @settings(max_examples=100, deadline=None)
    @given(
        d=_datos(),
        token=_tokens_usuario,
        hat=_hat,
        conf=_confianzas,
        cont=_sospechoso,
        duplicado=st.booleans(),
    )
    def test_mismo_resultado_en_siempre_y_adaptativo(self, d, token, hat, conf, cont, duplicado):
        a = _ejecutar(d, token, hat, "siempre", duplicado=duplicado, conf=conf, cont=cont)
        b = _ejecutar(d, token, hat, "adaptativo", duplicado=duplicado, conf=conf, cont=cont)
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# Pruebas de ejemplo de rechazo del Token_Automatico (tarea 7.4)
# **Validates: Requirements 6.3, 6.4, 6.5, 6.6, 6.9, 19.5**
# ---------------------------------------------------------------------------

def _factura(**cambios) -> dict:
    d = {
        "comercio": "Super Test", "fecha": AYER, "total": 20.0,
        "moneda": "USD", "categoria": CLOSED_CATEGORY_LIST[0],
    }
    d.update(cambios)
    return d


class TestRechazoTokenAutomaticoEjemplos(SinRedTestCase):
    TOKEN = "auto:abcdef12"

    def setUp(self) -> None:
        self._loop = asyncio.new_event_loop()
        self.addCleanup(self._loop.close)
        super().setUp()
        self._repo_orig, self._pol_orig = server._repo, server._policy
        self.addCleanup(self._restaurar)

    def _restaurar(self) -> None:
        server._repo, server._policy = self._repo_orig, self._pol_orig

    def test_factura_limpia_adaptativo_se_acepta(self):
        # Control: sin condiciones de rechazo, el token automático sí persiste.
        codigo, nuevas, _ = _ejecutar(_factura(), self.TOKEN, None, "adaptativo", conf=0.9, cont=False)
        self.assertIsNone(codigo)
        self.assertEqual(nuevas, 1)

    def test_monto_alto_rechazado(self):
        codigo, nuevas, _ = _ejecutar(
            _factura(total=150.0), self.TOKEN, None, "adaptativo", conf=0.9, cont=False
        )
        self.assertEqual(codigo, "HIGH_AMOUNT_CONFIRMATION_REQUIRED")
        self.assertEqual(nuevas, 0)

    def test_aritmetica_inconsistente_rechazada(self):
        d = _factura(subtotal=30.0, iva=1.0)
        codigo, nuevas, _ = _ejecutar(d, self.TOKEN, None, "adaptativo", conf=0.9, cont=False)
        self.assertEqual(codigo, "HUMAN_CONFIRMATION_REQUIRED")
        self.assertEqual(nuevas, 0)

    def test_duplicado_rechazado(self):
        codigo, nuevas, _ = _ejecutar(
            _factura(), self.TOKEN, None, "adaptativo", duplicado=True, conf=0.9, cont=False
        )
        self.assertEqual(codigo, "HUMAN_CONFIRMATION_REQUIRED")
        self.assertEqual(nuevas, 0)

    def test_confianza_ocr_baja_rechazada(self):
        codigo, nuevas, _ = _ejecutar(
            _factura(), self.TOKEN, None, "adaptativo", conf=UMBRAL_OCR - 0.01, cont=False
        )
        self.assertEqual(codigo, "HUMAN_CONFIRMATION_REQUIRED")
        self.assertEqual(nuevas, 0)

    def test_contenido_sospechoso_rechazado(self):
        codigo, nuevas, _ = _ejecutar(
            _factura(), self.TOKEN, None, "adaptativo", conf=0.9, cont=True
        )
        self.assertEqual(codigo, "HUMAN_CONFIRMATION_REQUIRED")
        self.assertEqual(nuevas, 0)

    def test_modo_siempre_rechaza_token_automatico(self):
        codigo, nuevas, _ = _ejecutar(
            _factura(), self.TOKEN, None, "siempre", conf=0.9, cont=False
        )
        self.assertEqual(codigo, "AUTOMATIC_TOKEN_NOT_ALLOWED")
        self.assertEqual(nuevas, 0)

    def test_handler_devuelve_is_error_y_sigue_aceptando_llamadas(self):
        handler = server.server.request_handlers[types.CallToolRequest]

        def llamar(args):
            req = types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(name="registrar_transaccion", arguments=args),
            )
            with contextlib.redirect_stdout(io.StringIO()):
                return self._loop.run_until_complete(handler(req)).root

        with tempfile.TemporaryDirectory() as tmp:
            repo = TransactionRepository(os.path.join(tmp, "t.db"))
            try:
                server._repo, server._policy = repo, _politica("adaptativo")
                rechazo = llamar(dict(
                    _factura(total=150.0), confirmation_token=self.TOKEN,
                    confianza_ocr=0.9, contenido_sospechoso=False,
                ))
                self.assertTrue(rechazo.isError)
                self.assertIn("HIGH_AMOUNT_CONFIRMATION_REQUIRED", rechazo.content[0].text)
                self.assertEqual(_contar(repo), 0)
                # El servidor sigue aceptando llamadas posteriores.
                ok = llamar(dict(
                    _factura(), confirmation_token=self.TOKEN,
                    confianza_ocr=0.9, contenido_sospechoso=False,
                ))
                self.assertFalse(ok.isError)
                self.assertEqual(_contar(repo), 1)
            finally:
                server._repo = self._repo_orig
                repo.close()


if __name__ == "__main__":
    unittest.main()
