from __future__ import annotations

import asyncio
from datetime import date

from django.core.management.base import BaseCommand

from gestion_riesgo.models import Inversionista, BalanceInversionista
from quant_deriv_bot.infra.deriv_ws import ClienteDerivWS


class Command(BaseCommand):
    help = "Sincroniza el balance real de cada inversionista desde la API de Deriv."

    def add_arguments(self, parser):
        parser.add_argument(
            "--inv-id",
            type=int,
            default=None,
            help="Solo sincronizar un inversionista específico por ID.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No guardar cambios, solo mostrar qué se haría.",
        )

    def handle(self, *args, **opts) -> None:
        inv_id = opts.get("inv_id")
        dry_run = opts.get("dry_run", False)

        if inv_id:
            invs = Inversionista.objects.filter(id=inv_id)
        else:
            invs = Inversionista.objects.filter(deriv_api_token__isnull=False).exclude(deriv_api_token="")

        if not invs.exists():
            self.stdout.write(f"{'[DRY-RUN] ' if dry_run else ''}No hay inversionistas con token de API configurado.")
            return

        self.stdout.write(f"{'[DRY-RUN] ' if dry_run else ''}Sincronizando {invs.count()} inversionista(s)...")

        for inv in invs:
            self.stdout.write(f"\n  → {inv.nombre or inv.user.username} (ID={inv.id})")
            if not inv.deriv_api_token:
                self.stdout.write(f"    ⚠ Sin token, omitido")
                continue

            balance_info = asyncio.run(_obtener_balance(inv.deriv_api_token, self))

            if balance_info is None:
                self.stdout.write(f"    ❌ No se pudo obtener balance")
                inv.observaciones = f"[{date.today()}] Error al sincronizar balance: token inválido o conexión fallida. {inv.observaciones}"[:500]
                if not dry_run:
                    inv.save(update_fields=["observaciones"])
                continue

            balance_val, currency = balance_info
            self.stdout.write(f"    Balance: {balance_val:.2f} {currency}")
            self.stdout.write(f"    Capital actual (BD): {inv.capital_actual:.2f}")

            if dry_run:
                self.stdout.write(f"    [DRY-RUN] Se actualizaría capital_actual={balance_val:.2f}")
                self.stdout.write(f"    [DRY-RUN] Se crearía BalanceInversionista para {date.today()}")
                continue

            capital_anterior = inv.capital_actual
            diferencia = balance_val - capital_anterior
            self.stdout.write(f"    Diferencia: {diferencia:+.2f}")

            inv.capital_actual = balance_val

            if diferencia != 0:
                ganancia_actual = inv.ganancia_acumulada
                nueva_ganancia = ganancia_actual + diferencia
                inv.ganancia_acumulada = max(0, nueva_ganancia)

            inv.save(update_fields=["capital_actual", "ganancia_acumulada", "updated_at"])

            hoy = date.today()
            snap_exists = BalanceInversionista.objects.filter(
                inversionista=inv, fecha=hoy
            ).exists()

            if snap_exists:
                BalanceInversionista.objects.filter(inversionista=inv, fecha=hoy).update(
                    capital=balance_val,
                    ganancia_acumulada=inv.ganancia_acumulada,
                    balance_deriv=balance_val,
                )
                self.stdout.write(f"    ✅ Snapshot de hoy actualizado")
            else:
                BalanceInversionista.objects.create(
                    inversionista=inv,
                    fecha=hoy,
                    capital=balance_val,
                    ganancia_acumulada=inv.ganancia_acumulada,
                    balance_deriv=balance_val,
                )
                self.stdout.write(f"    ✅ Snapshot diario creado ({hoy})")

        self.stdout.write(f"\n{'[DRY-RUN] ' if dry_run else ''}Sincronización completada.")


async def _obtener_balance(token: str, cmd: BaseCommand) -> tuple[float, str] | None:
    try:
        async with ClienteDerivWS(token=token) as cliente:
            await cliente.enviar({"balance": 1})
            respuesta = await cliente.recibir(timeout_segundos=15)

            if respuesta.get("error"):
                cmd.stdout.write(f"    ❌ Error Deriv: {respuesta['error']}")
                return None

            balance_info = respuesta.get("balance", {})
            if not balance_info:
                cmd.stdout.write(f"    ❌ Respuesta sin campo 'balance'")
                return None

            balance_val = float(balance_info.get("balance", 0))
            currency = str(balance_info.get("currency", "USD"))
            return (balance_val, currency)

    except asyncio.TimeoutError:
        cmd.stdout.write(f"    ❌ Timeout conectando a Deriv")
        return None
    except Exception as e:
        cmd.stdout.write(f"    ❌ Excepción: {e}")
        return None
