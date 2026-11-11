# -*- coding: utf-8 -*-
"""Bug condition exploration: ``main(argv=[])`` sin image_path.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**

Property 1 (design.md): sin ``image_path`` el CLI debe pedir la ruta (TTY) y
procesarla, o imprimir un uso con ``docker compose run`` y salir con codigo
distinto de cero, sin traza ni ``SystemExit`` de argparse.

En codigo SIN corregir estas pruebas DEBEN fallar (``SystemExit(2)``:
"the following arguments are required: image_path").
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, strategies as st

from agent import main as agent_main


class FakeStdin(io.StringIO):
    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:  # noqa: D401
        return self._tty


def _invoke(stdin_text: str, tty: bool):
    """Ejecuta main(argv=[]) con McpToolbox/run_cli parcheados.

    Devuelve (exit_code, stdout, stderr, run_cli_mock). Un SystemExit se
    propaga al llamador (eso es el bug).
    """
    fake_result = SimpleNamespace(status="success", termination_reason="ok", transaction_id=None)
    run_cli = MagicMock(return_value=fake_result)
    toolbox = MagicMock()
    toolbox.return_value.__enter__.return_value = SimpleNamespace(tools={})
    out, err = io.StringIO(), io.StringIO()
    with patch.object(agent_main, "McpToolbox", toolbox), \
            patch.object(agent_main, "run_cli", run_cli), \
            patch.object(agent_main, "_force_utf8", lambda: None), \
            patch("sys.stdin", FakeStdin(stdin_text, tty)), \
            patch("sys.stdout", out), patch("sys.stderr", err):
        code = agent_main.main(argv=[])
    return code, out.getvalue(), err.getvalue(), run_cli


def _assert_expected(code, out, err, run_cli, entered_path):
    if entered_path:  # prompt + procesamiento
        assert run_cli.call_count == 1
        assert run_cli.call_args.args[0] == entered_path
    else:  # uso Docker + codigo distinto de cero
        assert run_cli.call_count == 0
        assert "docker compose run" in (out + err)
        assert code != 0
        assert "Traceback" not in (out + err)


def test_no_tty_shows_usage_nonzero_exit():
    code, out, err, run_cli = _invoke("", tty=False)
    _assert_expected(code, out, err, run_cli, None)


def test_tty_with_path_prompts_and_processes():
    code, out, err, run_cli = _invoke("/app/facturas/a.jpg\n", tty=True)
    _assert_expected(code, out, err, run_cli, "/app/facturas/a.jpg")


def test_tty_empty_line_shows_usage():
    code, out, err, run_cli = _invoke("\n", tty=True)
    _assert_expected(code, out, err, run_cli, None)


def test_tty_eof_shows_usage():
    code, out, err, run_cli = _invoke("", tty=True)
    _assert_expected(code, out, err, run_cli, None)


_path = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zs", "Zl", "Zp")),
    min_size=1, max_size=30,
)


@settings(max_examples=25, deadline=None)
@given(path=_path)
def test_property_tty_path_is_processed(path):
    code, out, err, run_cli = _invoke(path + "\n", tty=True)
    _assert_expected(code, out, err, run_cli, path)


@settings(max_examples=25, deadline=None)
@given(text=st.one_of(st.just(""), st.text(alphabet=" \t", max_size=5).map(lambda s: s + "\n")),
       tty=st.booleans())
def test_property_empty_input_shows_usage(text, tty):
    code, out, err, run_cli = _invoke(text, tty=tty)
    _assert_expected(code, out, err, run_cli, None)


@settings(max_examples=25, deadline=None)
@given(text=st.text(max_size=20))
def test_property_non_tty_never_argparse_exit(text):
    code, out, err, run_cli = _invoke(text, tty=False)
    _assert_expected(code, out, err, run_cli, None)
