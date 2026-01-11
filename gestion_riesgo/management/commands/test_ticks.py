from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from gestion_riesgo.models import Cuenta, TickDerivSnapshot


class Command(BaseCommand):
    help = "Prueba crear un tick directamente en la BD para verificar que el modelo funciona."

    def handle(self, *args, **opts) -> None:  # noqa: ANN001
        cuenta = Cuenta.objects.first()
        if not cuenta:
            self.stdout.write("❌ No hay cuenta")
            return

        self.stdout.write("=" * 80)
        self.stdout.write("PRUEBA DE GUARDADO DE TICKS")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Cuenta ID: {cuenta.id}")
        self.stdout.write("")

        # Intentar crear un tick de prueba
        try:
            tick = TickDerivSnapshot.objects.create(
                cuenta=cuenta,
                precio=5803.50000,
                epoch=int(time.time()),
            )
            self.stdout.write(f"✅ Tick creado exitosamente: ID {tick.id}, precio {tick.precio:.5f}, epoch {tick.epoch}")
            
            # Verificar que se guardó
            tick_verificado = TickDerivSnapshot.objects.get(id=tick.id)
            self.stdout.write(f"✅ Tick verificado en BD: precio {tick_verificado.precio:.5f}")
            
            # Contar total
            total = TickDerivSnapshot.objects.filter(cuenta=cuenta).count()
            self.stdout.write(f"✅ Total ticks en BD: {total}")
            
        except Exception as e:
            import traceback
            self.stderr.write(f"❌ Error al crear tick: {e}\n{traceback.format_exc()}")
            return

        self.stdout.write("")
