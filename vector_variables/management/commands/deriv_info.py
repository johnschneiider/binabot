from __future__ import annotations

import asyncio
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS, obtener_duraciones_disponibles


class Command(BaseCommand):
    help = "Muestra información de la cuenta Deriv asociada al token (loginid/account_id, moneda, balance)."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument("--permitir-sin-venv", action="store_true")
        parser.add_argument(
            "--symbol",
            type=str,
            default="",
            help="Símbolo para consultar duraciones disponibles (ej: frxEURUSD, R_10)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN001
        if not options.get("permitir_sin_venv") and not self._en_entorno_virtual():
            raise CommandError("Activa `.venv` antes de correr `deriv_info`.")

        symbol = (options.get("symbol") or "").strip()
        if symbol:
            asyncio.run(self._run_durations(symbol))
            return

        if not settings.DERIV_API_TOKEN:
            raise CommandError("Configura DERIV_API_TOKEN en tu archivo .env antes de correr `deriv_info`.")

        asyncio.run(self._run())

    async def _run_durations(self, symbol: str) -> None:
        self.stdout.write(self.style.SUCCESS(f"=== DURACIONES PARA {symbol} ==="))
        async with ClienteDerivWS(token=settings.DERIV_API_TOKEN) as cliente:
            duraciones = await obtener_duraciones_disponibles(cliente, symbol)
            if duraciones:
                self.stdout.write(f"Duraciones válidas (ticks): {duraciones}")
            else:
                self.stdout.write(self.style.ERROR("No se pudieron obtener duraciones"))
                self.stdout.write("Nota: Los símbolos forex (frx*) pueden requerir cuenta real autenticada")

    async def _run(self) -> None:
        async with ClienteDerivWS(token=settings.DERIV_API_TOKEN) as cliente:
            # PEDIR BALANCE UNA VEZ (NO SUBSCRIBE) PARA MOSTRAR DATOS RÁPIDO.
            await cliente.enviar({"balance": 1})
            msg = await cliente.recibir(timeout_segundos=20)
            if msg.get("error"):
                raise CommandError(f"Deriv error: {msg['error']}")

            bal = msg.get("balance") or {}
            loginid = str(bal.get("loginid") or "")
            currency = str(bal.get("currency") or "")
            balance = bal.get("balance")

            self.stdout.write(self.style.SUCCESS("=== DERIV ACCOUNT INFO ==="))
            self.stdout.write(f"DERIV_ACCOUNT_ID (loginid): {loginid or '[no recibido]'}")
            self.stdout.write(f"Moneda: {currency or '[no recibido]'}")
            self.stdout.write(f"Balance: {balance if balance is not None else '[no recibido]'}")
            self.stdout.write("")
            self.stdout.write("Pega esto en tu .env si lo necesitas:")
            self.stdout.write(f"DERIV_ACCOUNT_ID={loginid}")

    @staticmethod
    def _en_entorno_virtual() -> bool:
        base = getattr(sys, "base_prefix", sys.prefix)
        return bool(sys.prefix != base)


