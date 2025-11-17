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
        # LÓGICA SIMPLIFICADA: Stop loss es un balance mínimo que solo sube
        # Si el balance sube, actualizar el stop loss (trailing stop loss)
        # Si el balance baja, el stop loss se mantiene fijo
        stop_loss_anterior = config.stop_loss_actual
        nuevo_stop_loss = config.calcular_stop_loss(config.balance_actual)
        
        # Solo actualizar stop_loss si el balance subió
        if nuevo_stop_loss > config.stop_loss_actual:
            config.stop_loss_actual = nuevo_stop_loss
            config.balance_stop_loss_base = config.balance_actual
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Balance subió, stop loss actualizado: "
                    f"${stop_loss_anterior} → ${config.stop_loss_actual}"
                )
            )
        elif config.stop_loss_actual <= 0:
            # Inicializar stop loss si no existe
            config.stop_loss_actual = nuevo_stop_loss
            config.balance_stop_loss_base = config.balance_actual
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Stop loss inicializado: ${config.stop_loss_actual}"
                )
            )
        else:
            # Balance bajó, stop loss se mantiene fijo
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Balance bajó, stop loss se mantiene fijo: ${config.stop_loss_actual}"
                )
            )
        
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
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ Stop loss (balance mínimo): ${config.stop_loss_actual}"
            )
        )
        self.stdout.write(f"  ✓ Balance actual: ${config.balance_actual}")
        
        if config.balance_actual <= config.stop_loss_actual:
            self.stdout.write(
                self.style.ERROR(
                    f"  ⚠ ALERTA: Balance ({config.balance_actual}) <= Stop loss ({config.stop_loss_actual})"
                )
            )
            self.stdout.write("  → El bot debería estar pausado")
        else:
            diferencia = config.balance_actual - config.stop_loss_actual
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Balance está ${diferencia} por encima del stop loss"
                )
            )
            self.stdout.write(
                f"  ✓ Si el balance baja a ${config.stop_loss_actual} o menos, el bot se pausará"
            )
        
        self.stdout.write(self.style.SUCCESS("\n✓ Corrección completada\n"))


