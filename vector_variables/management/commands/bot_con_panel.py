from __future__ import annotations

import asyncio
import sys

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from quant_deriv_bot.infra.dashboard_server import iniciar_dashboard
from vector_variables.management.commands.deriv_stream import Command as DerivStreamCommand
from vector_variables.management.commands.deriv_stream import _append_runtime_log


class Command(BaseCommand):
    help = "Corre BOT + DASHBOARD en una sola terminal (un solo proceso)."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--host", type=str, default="127.0.0.1", help="Host del dashboard (default 127.0.0.1).")
        parser.add_argument("--port", type=int, default=8000, help="Puerto del dashboard (default 8000).")
        parser.add_argument("--sin-migrar", action="store_true", help="No ejecutar migrate al iniciar.")

        # REENVIAR FLAGS DEL STREAM
        parser.add_argument("--symbol", type=str, default=None)
        parser.add_argument(
            "--symbols",
            type=str,
            default=None,
            help="Lista separada por comas (ej: R_10,R_100). Si no se pasa, usa R_10 y R_100 por defecto.",
        )
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
        # Compatibilidad:
        # - Si se pasa --symbol => corre SOLO ese
        # - Si se pasa --symbols => corre esa lista
        # - Si no se pasa nada => corre R_10 y R_100
        symbol = (options.get("symbol") or "").strip()
        symbols_raw = (options.get("symbols") or "").strip()
        if symbol:
            symbols = [symbol]
        elif symbols_raw:
            symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
        else:
            symbols = ["R_10", "R_100"]

        stream = DerivStreamCommand()
        stream.stdout = self.stdout
        stream.stderr = self.stderr

        # ===== MODO REAL (ROBUSTEZ EN PRODUCCIÓN) =====
        # En systemd es común dejar `--real` fijo en el ExecStart, pero alternar la confirmación
        # (DERIV_CONFIRMAR_REAL) desde .env para pausar trading real.
        # Si NO está confirmado, NO tumbar el servicio (eso rompe el dashboard y genera 502).
        want_real = bool(options.get("real"))
        real_confirmado = bool(getattr(settings, "DERIV_MODO_REAL", False)) and (
            str(getattr(settings, "DERIV_CONFIRMAR_REAL", "") or "").strip().upper() == "SI"
        )
        tiene_token = bool(getattr(settings, "DERIV_API_TOKEN", "") or "")
        ejecutar_real = bool(want_real and real_confirmado and tiene_token)
        if want_real and not ejecutar_real:
            msg = (
                "[BOOT] --real solicitado pero NO confirmado; iniciando en modo MONITOREO (sin órdenes). "
                f"DERIV_MODO_REAL={getattr(settings,'DERIV_MODO_REAL', None)} "
                f"DERIV_CONFIRMAR_REAL={getattr(settings,'DERIV_CONFIRMAR_REAL', None)!r} "
                f"token={'OK' if tiene_token else 'MISSING'}"
            )
            self.stderr.write(msg)
            _append_runtime_log(msg)

        asyncio.run(
            stream._run_multiple_symbols(
                symbols=symbols,
                max_ticks=int(options.get("max_ticks")),
                max_segundos=int(options.get("max_segundos")),
                max_reintentos=int(options.get("max_reintentos")),
                ilimitado=bool(options.get("ilimitado")),
                ejecutar_real=ejecutar_real,
            )
        )

    @staticmethod
    def _en_entorno_virtual() -> bool:
        base = getattr(sys, "base_prefix", sys.prefix)
        return bool(sys.prefix != base)


