"""Aislamiento de red para pruebas (Req. 18.6, 19.10).

``SinRedTestCase`` parchea ``socket.socket.connect`` y
``socket.create_connection`` para que cualquier intento de conexión falle
la prueba de inmediato.
"""

from __future__ import annotations

import socket
import unittest
from unittest import mock


class IntentoDeRedError(AssertionError):
    """Se intentó abrir una conexión de red durante una prueba."""


def _bloquear(*args, **kwargs):
    destino = args[1] if len(args) > 1 else args[0] if args else kwargs
    raise IntentoDeRedError(f"Intento de acceso a red bloqueado: {destino!r}")


class SinRedTestCase(unittest.TestCase):
    """Base para pruebas que no deben tocar la red."""

    def setUp(self) -> None:
        super().setUp()
        for destino in ("socket.socket.connect", "socket.create_connection"):
            parche = mock.patch(destino, side_effect=_bloquear)
            parche.start()
            self.addCleanup(parche.stop)
