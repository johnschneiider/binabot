from __future__ import annotations

import asyncio
import sys

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from quant_deriv_bot.infra.dashboard_server import iniciar_dashboard
from vector_variables.management.commands.deriv_stream import Command as DerivStreamCommand


class Command(BaseCommand):
    help = "Corre BOT + DASHBOARD en una sola terminal (un solo proceso)."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host del dashboard (default 127.0.0.1).")
        parser.add_argument("--port", type=int, default=8000, help="Puerto del dashboard (default 8000).")
        parser.add_argument("--sin-migrar", action="store_true", help="No ejecutar migrate al iniciar.")

        # REENVIAR FLAGS DEL STREAM
        parser.add_argument("--symbol", type=str, default=None)
        parser.add_argument("--max-ticks", type=int, default=2000)
        parser.add_argument("--max-segundos", type=int, default=300)
        parser.add_argument("--max-reintentos", type=int, default=10)
        parser.add_argument("--ilimitado", action="store_true")
        parser.add_argument("--permitir-sin-venv", action="store_true")
        parser.add_argument(
            "--real",
            action="store_true",
            help="Activa trading REAL (requiere DERIV_MODO_REAL=True y DERIV_CONFIRMAR_REAL=SI).",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        if not options.get("permitir_sin_venv") and not self._en_entorno_virtual():
            raise CommandError("Activa `.venv` antes de correr `bot_con_panel`.")

        if not options.get("sin_migrar"):
            call_command("migrate", interactive=False, verbosity=0)

        host = str(options.get("host"))
        port = int(options.get("port"))
        iniciar_dashboard(host=host, port=port)
        self.stdout.write(self.style.SUCCESS(f"Dashboard: http://{host}:{port}/"))

        # EJECUTAR STREAM EN ESTE MISMO PROCESO
        symbol = options.get("symbol")
        stream = DerivStreamCommand()
        stream.stdout = self.stdout
        stream.stderr = self.stderr

        asyncio.run(
            stream._run(
                (symbol or "").strip() or settings.DERIV_SYMBOL,
                max_ticks=int(options.get("max_ticks")),
                max_segundos=int(options.get("max_segundos")),
                max_reintentos=int(options.get("max_reintentos")),
                ilimitado=bool(options.get("ilimitado")),
                ejecutar_real=bool(options.get("real")),
            )
        )

    @staticmethod
    def _en_entorno_virtual() -> bool:
        base = getattr(sys, "base_prefix", sys.prefix)
        return bool(sys.prefix != base)


