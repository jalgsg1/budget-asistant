# -*- coding: utf-8 -*-
"""Property 2: Preservation - invocaciones con image_path (spec docker-agent-image-path).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from hypothesis import given, settings, strategies as st

from agent import main as cli

BACKEND_DIR = Path(__file__).resolve().parent.parent

EXIT_MAP = {"success": 0, "validation_error": 1, "user_abort": 2,
            "step_limit": 3, "token_limit": 3}

paths = st.text(min_size=1).filter(lambda s: s.strip() and not s.startswith("-") and "\x00" not in s)


class _FakeStdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty
        self.reads = 0

    def isatty(self) -> bool:
        return self._tty

    def readline(self) -> str:
        self.reads += 1
        raise AssertionError("stdin no debe leerse cuando hay image_path")

    read = readline


class _FakeToolbox:
    def __init__(self, user_id: str) -> None:
        self.tools = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _setup(monkeypatch, status: str, tty: bool):
    calls: list[str] = []

    def fake_run_cli(image_path, tools, io=None, policy=None, user_id=None, traces_dir=None):
        calls.append(image_path)
        return SimpleNamespace(status=status, termination_reason="x", transaction_id=None)

    stdin = _FakeStdin(tty)
    monkeypatch.setattr(cli, "McpToolbox", _FakeToolbox)
    monkeypatch.setattr(cli, "run_cli", fake_run_cli)
    monkeypatch.setattr(cli, "_force_utf8", lambda: None)
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    return calls, stdin


@settings(max_examples=50, deadline=None)
@given(ruta=paths, status=st.sampled_from(sorted(EXIT_MAP)), tty=st.booleans())
def test_argv_ruta_preserved(ruta, status, tty):
    mp = pytest.MonkeyPatch()
    try:
        calls, stdin = _setup(mp, status, tty)
        code = cli.main(argv=[ruta])
    finally:
        mp.undo()
    assert calls == [ruta]
    assert stdin.reads == 0
    assert code == EXIT_MAP[status]


@settings(max_examples=50, deadline=None)
@given(ruta=paths, status=st.sampled_from(sorted(EXIT_MAP)), tty=st.booleans())
def test_image_path_kwarg_no_stdin(ruta, status, tty):
    mp = pytest.MonkeyPatch()
    try:
        calls, stdin = _setup(mp, status, tty)
        code = cli.main(image_path=ruta)
    finally:
        mp.undo()
    assert calls == [ruta]
    assert stdin.reads == 0
    assert code == EXIT_MAP[status]


def test_exit_codes_map_unchanged():
    assert cli._EXIT_CODES == EXIT_MAP


# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((BACKEND_DIR / "docker-compose.yml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("svc", ["finanzas-mcp", "ocr-mcp", "api-pruebas"])
def test_compose_services_volumes_env(compose, svc):
    assert svc in compose["services"]
    s = compose["services"][svc]
    assert {"./data:/app/data", "./facturas:/app/facturas", "./traces:/app/traces"} <= set(s["volumes"])
    env = s["environment"]
    assert env["DB_PATH"] == "/app/data/facturas.db"
    assert env["INVOICES_DIR"] == "/app/facturas"
    assert env["TRACES_DIR"] == "/app/traces"
    assert env["MCP_USER_ID"] == "${MCP_USER_ID:-default_user}"


def test_compose_service_commands(compose):
    sv = compose["services"]
    # Los MCP corren por Streamable HTTP dentro de compose.
    assert sv["finanzas-mcp"]["command"][:3] == ["python", "-m", "finanzas_mcp.server"]
    assert "streamable-http" in sv["finanzas-mcp"]["command"]
    assert sv["ocr-mcp"]["command"][:3] == ["python", "-m", "ocr_mcp.server"]
    assert "streamable-http" in sv["ocr-mcp"]["command"]
    assert sv["api-pruebas"]["command"][:3] == ["python", "-m", "api_pruebas"]
    assert "gestor-facturas" in sv
