"""Pruebas estructurales del repositorio (Requisitos 18.1, 18.2, 18.7, 18.8, 18.9).

Usan solo análisis AST y lectura de archivos: sin red ni LLM.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

RAIZ: Path = Path(__file__).resolve().parent.parent
DIR_TESTS: Path = RAIZ / "tests"

MODULOS_SUELTOS: tuple[str, ...] = (
    "agent/hitl.py",
    "agent/contenido_sospechoso.py",
    "finanzas_mcp/business/hitl.py",
)
SERVIDORES_MCP: tuple[str, ...] = ("finanzas_mcp", "ocr_mcp")
METODOS_TEXTO: frozenset[str] = frozenset({"read_text", "write_text"})


def _py_de(directorio: str) -> list[Path]:
    return sorted(
        p for p in (RAIZ / directorio).rglob("*.py") if "__pycache__" not in p.parts
    )


def _modulos_nuevos() -> list[Path]:
    rutas = _py_de("baseline") + _py_de("eval")
    rutas += [RAIZ / m for m in MODULOS_SUELTOS]
    return rutas


def _arbol(ruta: Path) -> ast.Module:
    return ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))


def _rel(ruta: Path) -> str:
    return ruta.relative_to(RAIZ).as_posix()


def _funciones_sin_hints(arbol: ast.Module) -> list[str]:
    faltantes: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = nodo.args
        todos = a.posonlyargs + a.args + a.kwonlyargs
        if a.vararg:
            todos.append(a.vararg)
        if a.kwarg:
            todos.append(a.kwarg)
        for i, arg in enumerate(a.posonlyargs + a.args):
            if i == 0 and arg.arg in ("self", "cls"):
                todos.remove(arg)
        sin_tipo = [x.arg for x in todos if x.annotation is None]
        if sin_tipo:
            faltantes.append(f"{nodo.name}:{nodo.lineno} parámetros {sin_tipo}")
        if nodo.returns is None:
            faltantes.append(f"{nodo.name}:{nodo.lineno} sin tipo de retorno")
    return faltantes


def _modo_binario(llamada: ast.Call, pos_modo: int) -> bool:
    modo: ast.expr | None = None
    if len(llamada.args) > pos_modo:
        modo = llamada.args[pos_modo]
    for kw in llamada.keywords:
        if kw.arg == "mode":
            modo = kw.value
    return (
        isinstance(modo, ast.Constant)
        and isinstance(modo.value, str)
        and "b" in modo.value
    )


def _aperturas_sin_encoding(arbol: ast.Module) -> list[str]:
    faltantes: list[str] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        f = nodo.func
        es_open = (isinstance(f, ast.Name) and f.id == "open") or (
            isinstance(f, ast.Attribute) and f.attr == "open"
        )
        es_texto = isinstance(f, ast.Attribute) and f.attr in METODOS_TEXTO
        if not (es_open or es_texto):
            continue
        # open(path, mode) builtin: modo en args[1]; Path.open(mode): args[0].
        if es_open:
            pos = 1 if isinstance(f, ast.Name) else 0
            if _modo_binario(nodo, pos):
                continue
        if not any(kw.arg == "encoding" for kw in nodo.keywords):
            faltantes.append(f"línea {nodo.lineno}")
    return faltantes


def _usos_stdout(arbol: ast.Module) -> list[str]:
    usos: list[str] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            f = nodo.func
            if isinstance(f, ast.Name) and f.id == "print":
                destino = next((k.value for k in nodo.keywords if k.arg == "file"), None)
                a_stderr = (
                    isinstance(destino, ast.Attribute)
                    and destino.attr == "stderr"
                    and isinstance(destino.value, ast.Name)
                    and destino.value.id == "sys"
                )
                if not a_stderr:
                    usos.append(f"print sin file=sys.stderr en línea {nodo.lineno}")
            elif (
                isinstance(f, ast.Attribute)
                and f.attr in ("write", "writelines", "flush", "buffer")
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "stdout"
            ):
                usos.append(f"sys.stdout.{f.attr} en línea {nodo.lineno}")
    return usos


class TestEstructuraRepositorio(unittest.TestCase):
    def test_modulos_nuevos_existen(self) -> None:
        self.assertTrue(_py_de("baseline"), "baseline/ sin módulos .py")
        self.assertTrue(_py_de("eval"), "eval/ sin módulos .py")
        for m in MODULOS_SUELTOS:
            self.assertTrue((RAIZ / m).is_file(), f"falta {m}")

    def test_type_hints_en_todas_las_firmas(self) -> None:
        """Requisito 18.1."""
        errores: list[str] = []
        for ruta in _modulos_nuevos():
            errores += [f"{_rel(ruta)}: {e}" for e in _funciones_sin_hints(_arbol(ruta))]
        self.assertEqual(errores, [], "\n".join(errores))

    def test_encoding_utf8_en_apertura_de_archivos(self) -> None:
        """Requisito 18.1."""
        errores: list[str] = []
        for ruta in _modulos_nuevos():
            errores += [f"{_rel(ruta)}: {e}" for e in _aperturas_sin_encoding(_arbol(ruta))]
        self.assertEqual(errores, [], "\n".join(errores))

    def test_servidores_mcp_no_escriben_a_stdout(self) -> None:
        """Requisito 18.2."""
        errores: list[str] = []
        for paquete in SERVIDORES_MCP:
            for ruta in _py_de(paquete):
                errores += [f"{_rel(ruta)}: {e}" for e in _usos_stdout(_arbol(ruta))]
        self.assertEqual(errores, [], "\n".join(errores))

    def test_readme_baseline_declara_exclusion_de_seguridad(self) -> None:
        """Requisito 18.7."""
        readme = RAIZ / "baseline" / "README.md"
        self.assertTrue(readme.is_file())
        texto = readme.read_text(encoding="utf-8")
        self.assertIn(".kiro/steering/seguridad.md", texto)
        self.assertRegex(texto.lower(), r"no aplica|excluid|exclusi[oó]n")

    def test_scripts_eval_y_baseline_no_estan_bajo_tests(self) -> None:
        """Requisitos 18.8 y 18.9."""
        nombres = {p.name for p in _py_de("eval") + _py_de("baseline")}
        nombres -= {"__init__.py"}
        bajo_tests = [
            _rel(p)
            for p in DIR_TESTS.rglob("*.py")
            if "__pycache__" not in p.parts and p.name in nombres
        ]
        for sub in ("eval", "baseline"):
            if (DIR_TESTS / sub).exists():
                bajo_tests.append(f"tests/{sub}/")
        self.assertEqual(bajo_tests, [], f"scripts bajo tests/: {bajo_tests}")


if __name__ == "__main__":
    unittest.main()
