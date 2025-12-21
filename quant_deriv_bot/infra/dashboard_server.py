from __future__ import annotations

import threading
from dataclasses import dataclass
from socketserver import ThreadingMixIn
from typing import Optional
from wsgiref.simple_server import WSGIServer, make_server

from django.core.handlers.wsgi import WSGIHandler


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


@dataclass(frozen=True)
class ServidorDashboard:
    """
    SERVIDOR HTTP MÍNIMO (WSGI) PARA MOSTRAR EL DASHBOARD EN EL MISMO PROCESO.
    """

    host: str
    port: int
    thread: threading.Thread


def iniciar_dashboard(host: str = "127.0.0.1", port: int = 8000) -> ServidorDashboard:
    """
    INICIA UN SERVIDOR HTTP EN UN THREAD PARA PODER CORRER BOT + UI EN UNA SOLA TERMINAL.
    """
    handler = WSGIHandler()
    httpd = make_server(host, int(port), handler, server_class=_ThreadingWSGIServer)

    def _run() -> None:
        httpd.serve_forever()

    t = threading.Thread(target=_run, name="dashboard-http", daemon=True)
    t.start()
    return ServidorDashboard(host=host, port=int(port), thread=t)


