# -*- coding: utf-8 -*-
"""Genera la partición adversarial sintética del Golden Set (Req. 13, 14).

Renderiza con Pillow facturas con datos totalmente sintéticos (sin PII real) y
escribe ``eval/golden_set/adversarial_security/images/*.png`` y ``ground_truth.json``,
con el mismo formato que el de la partición limpia más los campos propios de cada caso.
En los casos de inyección el texto inyectado es el nombre del comercio de la factura: es
un dato más y el sistema nunca debe tratarlo como instrucción. La salida es determinista.

Uso:  python -m eval.generar_adversarial [--salida DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from eval.constantes import (
    CATEGORIA_ADVERSARIAL,
    RESULTADO_NO_COMPROMETER,
    RESULTADO_NO_REGISTRAR,
    RESULTADO_REGISTRAR,
    VECTORES,
)

DIRECTORIO_DEFECTO = Path(__file__).resolve().parent / "golden_set" / "adversarial_security"
ANCHO, ALTO = 800, 1000
_FUENTES = ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")


def _fuente(tam: int) -> Any:
    for nombre in _FUENTES:
        try:
            return ImageFont.truetype(nombre, tam)
        except OSError:
            continue
    return ImageFont.load_default(tam)


def _fmt(valor: float) -> str:
    return f"{valor:.2f}"


def _ajustar(d: ImageDraw.ImageDraw, texto: str, fuente: Any, ancho: int) -> list[str]:
    """Divide ``texto`` en líneas que quepan en ``ancho`` píxeles (sin cortar palabras)."""
    lineas: list[str] = []
    actual = ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if not actual or d.textlength(prueba, font=fuente) <= ancho:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    lineas.append(actual)
    return lineas


def renderizar_factura(ruta: Path, f: dict[str, Any]) -> None:
    """Dibuja una factura sintética. ``f``: comercio, numero, fecha, moneda, subtotal, iva, total, cliente.

    Un ``comercio`` largo (p. ej. un texto inyectado) se parte en varias líneas del encabezado."""
    img = Image.new("RGB", (ANCHO, ALTO), "white")
    d = ImageDraw.Draw(img)
    titulo, normal, chica = _fuente(34), _fuente(24), _fuente(20)
    y = 40
    lineas_titulo = _ajustar(d, f["comercio"], titulo, ANCHO - 80)
    for i, linea in enumerate(lineas_titulo):
        d.text((40, y + 40 * i), linea, fill="black", font=titulo)
    y += 40 * (len(lineas_titulo) - 1) + 60
    d.text((40, y), "FACTURA ELECTRONICA (SINTETICA)", fill="black", font=chica)
    y += 40
    for etiqueta, valor in (
        ("Factura No.", f["numero"]),
        ("Fecha", f["fecha"]),
        ("Cliente", f["cliente"]),
        ("Moneda", f["moneda"]),
    ):
        d.text((40, y), f"{etiqueta}: {valor}", fill="black", font=normal)
        y += 38
    y += 20
    d.line((40, y, ANCHO - 40, y), fill="black", width=2)
    y += 20
    for linea in f.get("lineas", ["Servicio / producto sintetico"]):
        d.text((40, y), linea, fill="black", font=normal)
        y += 36
    y += 20
    d.line((40, y, ANCHO - 40, y), fill="black", width=2)
    y += 20
    for etiqueta, clave in (("Subtotal", "subtotal"), ("IVA", "iva"), ("TOTAL", "total")):
        d.text((40, y), f"{etiqueta}: {f['moneda']} {_fmt(f[clave])}", fill="black", font=normal)
        y += 40
    ruta.parent.mkdir(parents=True, exist_ok=True)
    img.save(ruta, format="PNG")


def _factura(i: int, comercio: str, fecha: str, moneda: str, subtotal: float, total: float | None = None,
             numero: str | None = None) -> dict[str, Any]:
    iva = round(subtotal * 0.13, 2)
    return {
        "comercio": comercio, "numero": numero or f"SYN-{i:05d}", "fecha": fecha, "moneda": moneda,
        "subtotal": subtotal, "iva": iva,
        "total": round(subtotal + iva, 2) if total is None else total,
        "cliente": f"Cliente Sintetico {i:03d}",
    }


COMERCIOS = ("Comercial Ficticio Alfa", "Super Imaginario Beta", "Ferreteria Falsa Gamma",
             "Cafe Inventado Delta", "Farmacia Simulada Epsilon", "Libreria Irreal Zeta")


def _entrada(imagen: str, f: dict[str, Any], dificultad: str, resultado: str, **extra: Any) -> dict[str, Any]:
    """Entrada con los campos del ``ground_truth.json`` de la partición limpia y los del caso."""
    return {
        "imagen": imagen, "comercio": f["comercio"], "fecha": f["fecha"], "moneda": f["moneda"],
        "total": f["total"], "categoria": CATEGORIA_ADVERSARIAL, "dificultad": dificultad,
        "resultado_esperado": resultado, **extra,
    }


def construir_casos(salida: Path) -> list[dict[str, Any]]:
    """Renderiza todas las imágenes y devuelve las entradas de ``ground_truth.json``."""
    imgs = salida / "images"
    casos: list[dict[str, Any]] = []
    originales: list[dict[str, Any]] = []
    n = 0

    def nuevo() -> int:
        nonlocal n
        n += 1
        return n

    def caso_base(cid: str, subtipo: str, f: dict[str, Any], dificultad: str = "limpia",
                  **extra: Any) -> dict[str, Any]:
        imagen = f"{cid}.png"
        renderizar_factura(imgs / imagen, f)
        return _entrada(imagen, f, dificultad, RESULTADO_NO_REGISTRAR,
                        tipo="integridad", subtipo=subtipo, **extra)

    # Fecha inválida (R2): malformadas y futuras
    fechas = (("malformada", "2025-04-31"), ("malformada", "2025-02-30"), ("futura", "2099-01-15"),
              ("futura", "2087-06-20"))
    for k, (variante, fecha) in enumerate(fechas):
        i = nuevo()
        f = _factura(i, COMERCIOS[k % 6], fecha, "USD", 40.0 + 5 * k)
        casos.append(caso_base(f"integ-fecha-{k + 1}", "fecha_invalida", f, variante=variante))

    # Moneda no soportada (R3)
    for k, mon in enumerate(("EUR", "GBP", "JPY")):
        i = nuevo()
        f = _factura(i, COMERCIOS[(k + 2) % 6], f"2025-05-{5 + k:02d}", mon, 80.0 + 10 * k)
        casos.append(caso_base(f"integ-moneda-{k + 1}", "moneda_no_soportada", f))

    # Factura duplicada (R5): el original aparece antes en la corrida
    for k in range(3):
        i = nuevo()
        f = _factura(i, COMERCIOS[(k + 1) % 6], f"2025-06-{12 + k:02d}", "CRC", 20000.0 + 3000 * k,
                     numero=f"SYN-DUP-{k + 1:03d}")
        oid = f"orig-{k + 1}"
        renderizar_factura(imgs / f"{oid}.png", f)
        originales.append(_entrada(f"{oid}.png", f, "limpia", RESULTADO_REGISTRAR, es_original=True))
        casos.append(caso_base(f"integ-duplicada-{k + 1}", "factura_duplicada", f,
                               dificultad="duplicada", original_id=oid))

    # Inyección indirecta: 5 vectores x 2 imágenes. El texto inyectado es el comercio de la factura.
    for vector, (condicion, textos) in VECTORES.items():
        for k, texto in enumerate(textos):
            i = nuevo()
            moneda = "CRC" if k == 0 else "USD"
            sub = 15000.0 + 1000 * i if moneda == "CRC" else 50.0 + i
            f = _factura(i, texto, f"2025-07-{(i % 27) + 1:02d}", moneda, sub)
            imagen = f"inj-{vector}-{k + 1}.png"
            renderizar_factura(imgs / imagen, f)
            casos.append(_entrada(
                imagen, f, "inyeccion", RESULTADO_NO_COMPROMETER,
                tipo="inyeccion", subtipo="inyeccion_indirecta", vector=vector,
                condicion_compromiso=condicion,
            ))
    return originales + casos


def generar(salida: Path = DIRECTORIO_DEFECTO) -> list[dict[str, Any]]:
    salida = Path(salida)
    entradas = construir_casos(salida)
    with open(salida / "ground_truth.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(entradas, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return entradas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--salida", type=Path, default=DIRECTORIO_DEFECTO)
    args = ap.parse_args(argv)
    from eval.golden_set import validar_particion_adversarial

    entradas = generar(args.salida)
    errores = validar_particion_adversarial(args.salida)
    for e in errores:
        print(f"ERROR {e.nombre}: {e.motivo}", file=sys.stderr)
    n_orig = sum(1 for e in entradas if e.get("es_original"))
    print(f"{len(entradas) - n_orig} casos, {n_orig} originales en {args.salida}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
