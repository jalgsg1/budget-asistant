# -*- coding: utf-8 -*-
"""Lanzador: ``python -m api_pruebas [--host 127.0.0.1] [--port 8000]``."""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> None:
    import uvicorn

    from api_pruebas.app import advertencia_red

    parser = argparse.ArgumentParser(prog="api_pruebas")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    aviso = advertencia_red(args.host)
    if aviso:
        print(aviso, file=sys.stderr)
    os.environ["API_HOST"] = args.host
    uvicorn.run("api_pruebas.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
