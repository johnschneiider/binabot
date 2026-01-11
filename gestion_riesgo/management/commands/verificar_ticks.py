from __future__ import annotations

from django.core.management.base import BaseCommand
from gestion_riesgo.models import Cuenta, TickDerivSnapshot


class Command(BaseCommand):
    help = "Verifica que los ticks se estén guardando correctamente en la base de datos."

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        cuenta = Cuenta.objects.first()
        if not cuenta:
            self.stdout.write("❌ No hay cuenta configurada.")
            return

        self.stdout.write("=" * 80)
        self.stdout.write("VERIFICACIÓN DE TICKS")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Cuenta ID: {cuenta.id}")
        self.stdout.write(f"Símbolo: {cuenta.simbolo}")
        self.stdout.write("")

        # Contar ticks
        total_ticks = TickDerivSnapshot.objects.filter(cuenta=cuenta).count()
        self.stdout.write(f"Total ticks en BD: {total_ticks}")

        if total_ticks > 0:
            # Últimos 5 ticks
            ultimos = TickDerivSnapshot.objects.filter(cuenta=cuenta).order_by("-epoch")[:5]
            self.stdout.write("\nÚltimos 5 ticks:")
            for tick in ultimos:
                self.stdout.write(f"  Epoch: {tick.epoch}, Precio: {tick.precio:.5f}, Creado: {tick.created_at}")

            # Verificar que no haya más de 50
            if total_ticks > 50:
                self.stdout.write(f"\n⚠️  ADVERTENCIA: Hay {total_ticks} ticks (debería haber máximo 50)")
                self.stdout.write("   Ejecuta limpieza manual si es necesario")
            else:
                self.stdout.write(f"\n✅ Ticks dentro del límite ({total_ticks}/50)")
        else:
            self.stdout.write("\n⚠️  No hay ticks en la base de datos")
            self.stdout.write("   Verifica que el bot esté ejecutándose y recibiendo ticks")
            self.stdout.write("   Revisa los logs del bot para errores al guardar ticks")

        self.stdout.write("")
