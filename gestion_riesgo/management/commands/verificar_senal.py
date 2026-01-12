from __future__ import annotations

from django.core.management.base import BaseCommand
from gestion_riesgo.models import Cuenta


class Command(BaseCommand):
    help = "Verifica el estado actual de la señal en la BD."

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        # Mostrar todas las cuentas primero
        todas_cuentas = Cuenta.objects.all().order_by("-updated_at")
        if not todas_cuentas.exists():
            self.stdout.write("❌ No hay cuentas")
            return

        self.stdout.write("=" * 80)
        self.stdout.write("TODAS LAS CUENTAS")
        self.stdout.write("=" * 80)
        for c in todas_cuentas:
            self.stdout.write(f"  Cuenta ID: {c.id} | Símbolo: {c.simbolo} | Última actualización: {c.updated_at}")
        self.stdout.write("")

        # Mostrar la cuenta más recientemente actualizada (la que está operando)
        cuenta = todas_cuentas.first()
        
        self.stdout.write("=" * 80)
        self.stdout.write("ESTADO DE SEÑAL EN BD (CUENTA MÁS RECIENTE)")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Cuenta ID: {cuenta.id}")
        self.stdout.write(f"Símbolo: {cuenta.simbolo}")
        self.stdout.write("")
        self.stdout.write(f"Señal valor: {cuenta.senal_valor}")
        self.stdout.write(f"Señal decisión: {cuenta.senal_decision}")
        self.stdout.write(f"Último precio: {cuenta.ultimo_precio}")
        self.stdout.write(f"Último tick epoch: {cuenta.ultimo_tick_epoch}")
        self.stdout.write(f"Última actualización: {cuenta.updated_at}")
        self.stdout.write("")
        self.stdout.write("Top contribuciones:")
        if cuenta.senal_top_contribuciones:
            for i, contrib in enumerate(cuenta.senal_top_contribuciones[:5], 1):
                var = contrib.get("variable", "—")
                contrib_val = contrib.get("contribucion", 0)
                self.stdout.write(f"  {i}. {var}: {contrib_val:.6f}")
        else:
            self.stdout.write("  —")
        self.stdout.write("")
