"""
Comando URGENTE para corregir el stop loss en la base de datos.
Asegura que el stop loss esté fijo basado en el balance_stop_loss_base más alto.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from core.models import ConfiguracionBot


class Command(BaseCommand):
    help = "URGENTE: Corrige el stop loss para que nunca baje con pérdidas"

    def handle(self, *args, **options):
        config = ConfiguracionBot.objects.first()
        
        if not config:
            self.stdout.write(self.style.ERROR("No hay configuración del bot"))
            return
        
        self.stdout.write(self.style.WARNING("\n" + "="*80))
        self.stdout.write(self.style.WARNING("CORRECCIÓN URGENTE DE STOP LOSS"))
        self.stdout.write(self.style.WARNING("="*80))
        
        self.stdout.write(f"\nEstado actual:")
        self.stdout.write(f"  Balance actual: ${config.balance_actual}")
        self.stdout.write(f"  Balance stop loss base: ${config.balance_stop_loss_base}")
        self.stdout.write(f"  Stop loss actual: ${config.stop_loss_actual}")
        self.stdout.write(f"  Pérdida acumulada: ${config.perdida_acumulada}")
        
        # Asegurar que balance_stop_loss_base nunca baje
        balance_stop_loss_base_original = config.balance_stop_loss_base
        
        # Si el balance actual es mayor que balance_stop_loss_base, actualizarlo
        if config.balance_actual > config.balance_stop_loss_base:
            config.balance_stop_loss_base = config.balance_actual
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Actualizado balance_stop_loss_base: "
                    f"${balance_stop_loss_base_original} → ${config.balance_stop_loss_base}"
                )
            )
        
        # Recalcular stop_loss_actual basado en balance_stop_loss_base
        stop_loss_anterior = config.stop_loss_actual
        config.stop_loss_actual = config.calcular_stop_loss(config.balance_stop_loss_base)
        
        # Recalcular pérdida acumulada
        perdida_anterior = config.perdida_acumulada
        perdida_calculada = config.balance_stop_loss_base - config.balance_actual
        if perdida_calculada < 0:
            perdida_calculada = Decimal("0.00")
        config.perdida_acumulada = perdida_calculada.quantize(Decimal("0.01"))
        
        self.stdout.write(f"\nCorrecciones aplicadas:")
        if stop_loss_anterior != config.stop_loss_actual:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Stop loss corregido: ${stop_loss_anterior} → ${config.stop_loss_actual}"
                )
            )
        else:
            self.stdout.write(f"  ✓ Stop loss ya estaba correcto: ${config.stop_loss_actual}")
        
        if perdida_anterior != config.perdida_acumulada:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Pérdida acumulada actualizada: ${perdida_anterior} → ${config.perdida_acumulada}"
                )
            )
        
        config.save(
            update_fields=[
                "balance_stop_loss_base",
                "stop_loss_actual",
                "perdida_acumulada",
                "ultima_actualizacion",
            ]
        )
        
        self.stdout.write(f"\nEstado final:")
        self.stdout.write(f"  Balance actual: ${config.balance_actual}")
        self.stdout.write(f"  Balance stop loss base: ${config.balance_stop_loss_base}")
        self.stdout.write(f"  Stop loss actual: ${config.stop_loss_actual}")
        self.stdout.write(f"  Pérdida acumulada: ${config.perdida_acumulada}")
        
        # Verificar lógica
        self.stdout.write(f"\nVerificación:")
        if config.balance_actual <= config.balance_stop_loss_base:
            diferencia = config.balance_stop_loss_base - config.balance_actual
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Stop loss fijo en: ${config.stop_loss_actual}"
                )
            )
            self.stdout.write(
                f"  ✓ Si la pérdida acumulada alcanza ${config.stop_loss_actual}, el bot se pausará"
            )
            self.stdout.write(f"  ✓ Pérdida actual: ${diferencia}")
            self.stdout.write(
                f"  ✓ Restante hasta stop loss: ${config.stop_loss_actual - diferencia}"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ Balance actual ({config.balance_actual}) > "
                    f"Balance stop loss base ({config.balance_stop_loss_base})"
                )
            )
            self.stdout.write("  → Esto debería actualizar el stop loss base")
        
        self.stdout.write(self.style.SUCCESS("\n✓ Corrección completada\n"))

