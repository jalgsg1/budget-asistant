# -*- coding: utf-8 -*-
"""eval/benchmark.py: CLI del experimento (Req. 15, 17).

Uso: ``python -m eval.benchmark [--limite N] [--sistemas ...] [--recalcular] [--salida DIR]``

Orden: argumentos, ``--recalcular``, claves, Golden Set, ``ordenar_casos``,
ejecución, informes. Nada se escribe hasta que todas las corridas terminan, así
que una interrupción no deja resultados parciales.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval.constantes import SISTEMAS as SISTEMAS_VALIDOS

RAIZ = Path(__file__).resolve().parent.parent
DIR_EVAL = Path(__file__).resolve().parent
DIR_LIMPIA = DIR_EVAL / "golden_set" / "clean_manual"
DIR_ADVERSARIAL = DIR_EVAL / "golden_set" / "adversarial_security"
RUTA_INJECTION_ANALYSIS = RAIZ / "security" / "injection_analysis.md"
NOMBRE_RESULTADOS = "resultados_paper.json"
NOMBRE_TABLA = "tabla_comparativa.md"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ARGUMENTOS = 2
EXIT_INTERRUMPIDO = 130


class ErrorCli(Exception):
    """Error de uso o de precondición; el mensaje va a stderr y el código a ``codigo``."""

    def __init__(self, mensaje: str, codigo: int = EXIT_ERROR) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> "None":  # type: ignore[override]
        raise ErrorCli(f"Argumentos inválidos: {message}", EXIT_ARGUMENTOS)


def construir_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m eval.benchmark", description="Benchmark de los tres sistemas.")
    p.add_argument("--limite", default=None, help="entero >= 1: facturas por partición")
    p.add_argument("--sistemas", nargs="+", default=None,
                   help="sistemas a ejecutar: " + ", ".join(SISTEMAS_VALIDOS))
    p.add_argument("--recalcular", action="store_true",
                   help="recalcula métricas e informes desde resultados_paper.json, sin LLM")
    p.add_argument("--salida", default=str(DIR_EVAL), help="directorio de salida (defecto: eval/)")
    return p


def validar_argumentos(ns: argparse.Namespace) -> tuple[int | None, list[str], Path]:
    """Devuelve (limite, sistemas, salida) o lanza ``ErrorCli``."""
    limite: int | None = None
    if ns.limite is not None:
        try:
            limite = int(str(ns.limite).strip())
        except ValueError:
            limite = None
        if limite is None or limite < 1:
            raise ErrorCli(
                f"Argumento --limite inválido: '{ns.limite}'. Debe ser un entero >= 1.",
                EXIT_ARGUMENTOS)
    sistemas = list(SISTEMAS_VALIDOS) if ns.sistemas is None else list(ns.sistemas)
    malos = [s for s in sistemas if s not in SISTEMAS_VALIDOS]
    if malos:
        raise ErrorCli(
            f"Argumento --sistemas inválido: {', '.join(malos)}. "
            f"Valores aceptados: {', '.join(SISTEMAS_VALIDOS)}.", EXIT_ARGUMENTOS)
    sistemas = [s for s in SISTEMAS_VALIDOS if s in sistemas]  # orden canónico, sin repetidos
    if not str(ns.salida).strip():
        raise ErrorCli("Argumento --salida inválido: está vacío.", EXIT_ARGUMENTOS)
    return limite, sistemas, Path(ns.salida)


def _cargar_env(ruta: Path) -> None:
    """Lee un .env simple sin sobrescribir variables ya definidas (solo lectura)."""
    try:
        with open(ruta, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                k, v = linea.split("=", 1)
                k = k.strip()
                v = v.strip()
                if v[:1] in ('"', "'") and v.find(v[0], 1) > 0:
                    v = v[1:v.find(v[0], 1)]
                else:
                    v = v.split(" #", 1)[0].split("\t#", 1)[0].strip()
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------

def _enriquecer(registros: Sequence[Any], extras: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict]:
    """Dicts de registros con ``vector`` y ``texto_inyectado`` (no están en RegistroFactura)."""
    salida = []
    for r in registros:
        d = r.a_dict()
        if d.get("tipo_caso") == "inyeccion":
            extra = extras.get((d["particion"], d["id"]), {})
            d["vector"] = extra.get("vector")
            d["texto_inyectado"] = extra.get("texto_inyectado")
        salida.append(d)
    return salida


def _escribir_informes(resultados: dict, registros: Sequence[Mapping[str, Any]], salida: Path) -> None:
    from eval.informes import (
        MarcasBenchError, _escribir_texto_atomico, actualizar_injection_analysis,
        escribir_json_atomico, formatear_tabla,
    )
    from eval.metricas import calcular_todo

    tabla = formatear_tabla(calcular_todo(list(registros)))
    escribir_json_atomico(resultados, salida / NOMBRE_RESULTADOS)
    _escribir_texto_atomico(tabla, salida / NOMBRE_TABLA)
    if RUTA_INJECTION_ANALYSIS.is_file():
        try:
            actualizar_injection_analysis(registros, RUTA_INJECTION_ANALYSIS)
        except (MarcasBenchError, OSError) as exc:
            print(f"Aviso: no se actualizó injection_analysis.md ({exc})", file=sys.stderr)
    print(f"Resultados: {salida / NOMBRE_RESULTADOS}")
    print(f"Tabla: {salida / NOMBRE_TABLA}")


def recalcular(salida: Path) -> int:
    """Recalcula métricas desde el JSON existente. No usa claves, BD ni LLM (Req. 17.7, 17.8)."""
    from eval.informes import ResultadosInvalidosError, leer_resultados
    from eval.metricas import calcular_todo

    try:
        datos = leer_resultados(salida / NOMBRE_RESULTADOS)
    except ResultadosInvalidosError as exc:
        raise ErrorCli(f"--recalcular no es posible: {exc}") from exc
    registros = datos["registros"]
    todo = calcular_todo(registros)
    datos["metricas"] = {s: d["metricas"] for s, d in todo.items()}
    datos["conteos"] = {s: d["conteos"] for s, d in todo.items()}
    _escribir_informes(datos, registros, salida)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------

def _validar_golden_set() -> None:
    import json

    from eval.golden_set import validar_manifiesto, validar_particion_limpia

    errores = list(validar_particion_limpia(DIR_LIMPIA))
    ruta_m = DIR_ADVERSARIAL / "adversarial_manifest.json"
    try:
        with open(ruta_m, encoding="utf-8") as fh:
            manifiesto = json.load(fh)
        errores += validar_manifiesto(manifiesto, DIR_ADVERSARIAL)
    except (OSError, ValueError) as exc:
        from eval.golden_set import ErrorValidacion
        errores.append(ErrorValidacion("adversarial_manifest.json", f"no se pudo leer: {type(exc).__name__}"))
    if errores:
        lineas = "\n".join(f"  - {e.nombre}: {e.motivo}" for e in errores)
        raise ErrorCli(f"El Golden Set no es válido:\n{lineas}")


def ejecutar(limite: int | None, sistemas: Sequence[str], salida: Path) -> int:
    from baseline.baseline_naive import SYSTEM_PROMPT_NAIVE
    from baseline.baseline_prompt_guarded import SYSTEM_PROMPT_GUARDED
    from baseline.llm import ClienteLangChain, ConfigLlmError, resolver_config_llm
    from eval import runner
    from eval.golden_set import cargar_particion_adversarial, cargar_particion_limpia
    from eval.informes import construir_resultados

    _cargar_env(RAIZ / ".env")
    try:
        config = resolver_config_llm(os.environ)
    except ConfigLlmError as exc:
        raise ErrorCli(f"Configuración del LLM incompleta: {exc}") from exc

    _validar_golden_set()

    casos_adv, originales = cargar_particion_adversarial(DIR_ADVERSARIAL)
    try:
        items_adv = runner.ordenar_casos(casos_adv, originales, limite)
    except runner.OrdenError as exc:
        raise ErrorCli(
            "No se puede garantizar el original de los duplicados: " + ", ".join(exc.ids)
        ) from exc
    items_limpios = runner.items_limpios(cargar_particion_limpia(DIR_LIMPIA), limite)
    extras = {
        ("adversarial", c.id): {"vector": c.vector, "texto_inyectado": c.texto_inyectado}
        for c in casos_adv
    }

    prompts = {"baseline_naive": SYSTEM_PROMPT_NAIVE, "baseline_prompt_guarded": SYSTEM_PROMPT_GUARDED}
    cliente = None
    if any(s in prompts for s in sistemas):
        cliente = ClienteLangChain(config)

    registros = []
    for sistema in sistemas:
        for particion, items in (("limpia", items_limpios), ("adversarial", items_adv)):
            print(f"[benchmark] {sistema} / {particion}: {len(items)} facturas", file=sys.stderr)
            if sistema == "arquitectura_mcp":
                registros += runner.correr_arquitectura(
                    items, particion, proveedor=config.proveedor, modelo=config.modelo)
            else:
                registros += runner.correr_baseline(sistema, prompts[sistema], cliente, items, particion)

    dicts = _enriquecer(registros, extras)
    resultados = construir_resultados(
        dicts,
        {"limite": limite, "sistemas": list(sistemas)},
        config.proveedor, config.modelo,
        runner.PoliticaRespuestasConfirmarTodo.descripcion(),
    )
    _escribir_informes(resultados, dicts, salida)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        ns = construir_parser().parse_args(argv)
        limite, sistemas, salida = validar_argumentos(ns)
        if ns.recalcular:
            return recalcular(salida)
        return ejecutar(limite, sistemas, salida)
    except ErrorCli as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.codigo
    except KeyboardInterrupt:
        print("Interrumpido: no se escribieron resultados parciales.", file=sys.stderr)
        return EXIT_INTERRUMPIDO


if __name__ == "__main__":
    sys.exit(main())
