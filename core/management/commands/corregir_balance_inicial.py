import time
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.utils import OperationalError

from core.services import GestorBotCore
from historial.models import Operacion


class Command(BaseCommand):
    help = "Corrige el balance inicial (balance_meta_base) basándose en el cálculo de retroceso."

    def add_arguments(self, parser):
        parser.add_argument(
            "--balance-inicial",
            type=float,
            help="Balance inicial a establecer (si no se proporciona, se calcula automáticamente)",
        )
        parser.add_argument(
            "--confirmar",
            action="store_true",
            help="Confirma la corrección sin preguntar",
        )

    def handle(self, *args, **options):
        gestor = GestorBotCore()
        config = gestor.configuracion

        # Obtener balance real desde API
        try:
            from integracion_deriv.client import obtener_balance_sync

            respuesta = obtener_balance_sync()
            balance_info = respuesta.get("balance", {})
            balance_real = Decimal(str(balance_info.get("balance", "0")))
        except Exception as exc:
            raise CommandError(f"Error al obtener balance de Deriv: {exc}")

        # Calcular total de beneficios
        operaciones_reales = Operacion.objetos.reales().exclude(
            resultado=Operacion.Resultado.PENDIENTE
        )
        total_beneficios = sum(op.beneficio for op in operaciones_reales)

        # Calcular balance inicial
        if options["balance_inicial"]:
            balance_inicial_nuevo = Decimal(str(options["balance_inicial"]))
        else:
            # Calcular automáticamente por retroceso
            balance_inicial_nuevo = (balance_real - total_beneficios).quantize(
                Decimal("0.01")
            )

        balance_inicial_actual = config.balance_meta_base
        diferencia = balance_inicial_nuevo - balance_inicial_actual

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("CORRECCIÓN DE BALANCE INICIAL"))
        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write("")

        self.stdout.write("INFORMACIÓN ACTUAL:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"Balance real (Deriv API):        US$ {balance_real:,.2f}")
        self.stdout.write(f"Total beneficios operaciones:     US$ {total_beneficios:,.2f}")
        self.stdout.write(f"Balance inicial actual:           US$ {balance_inicial_actual:,.2f}")
        self.stdout.write("")

        self.stdout.write("CÁLCULO PROPUESTO:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"Balance inicial nuevo:            US$ {balance_inicial_nuevo:,.2f}")
        self.stdout.write(f"Diferencia:                        US$ {diferencia:,.2f}")
        self.stdout.write("")

        # Verificar el nuevo cálculo
        balance_esperado_nuevo = (balance_inicial_nuevo + total_beneficios).quantize(
            Decimal("0.01")
        )
        diferencia_esperada = balance_real - balance_esperado_nuevo

        self.stdout.write("VERIFICACIÓN:")
        self.stdout.write("-" * 80)
        self.stdout.write(
            f"Balance esperado con nuevo inicial: US$ {balance_esperado_nuevo:,.2f}"
        )
        self.stdout.write(f"Balance real:                     US$ {balance_real:,.2f}")
        if abs(diferencia_esperada) <= Decimal("0.01"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Diferencia después de corrección: US$ {diferencia_esperada:,.2f} (consistente)"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  Diferencia después de corrección: US$ {diferencia_esperada:,.2f}"
                )
            )
        self.stdout.write("")

        if not options["confirmar"]:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  Esta acción actualizará el balance_meta_base y balance_stop_loss_base."
                )
            )
            self.stdout.write(
                "   Esto afectará el cálculo de metas y stop loss futuros."
            )
            self.stdout.write("")
            confirmacion = input("¿Deseas continuar? (sí/no): ")
            if confirmacion.lower() not in ["sí", "si", "yes", "y", "s"]:
                self.stdout.write(self.style.ERROR("Operación cancelada."))
                return

        # Aplicar corrección con reintentos
        max_intentos = 5
        tiempo_espera = 1  # segundos
        
        for intento in range(1, max_intentos + 1):
            try:
                with transaction.atomic():
                    # Refrescar desde la BD para evitar conflictos
                    config.refresh_from_db()
                    config.balance_meta_base = balance_inicial_nuevo
                    config.balance_stop_loss_base = balance_inicial_nuevo
                    config.meta_actual = config.calcular_meta(balance_inicial_nuevo)
                    config.stop_loss_actual = config.calcular_stop_loss(balance_inicial_nuevo)
                    config.save(
                        update_fields=[
                            "balance_meta_base",
                            "balance_stop_loss_base",
                            "meta_actual",
                            "stop_loss_actual",
                            "ultima_actualizacion",
                        ]
                    )
                break  # Éxito, salir del loop
            except OperationalError as e:
                if "database is locked" in str(e).lower() and intento < max_intentos:
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  Base de datos bloqueada (intento {intento}/{max_intentos}). "
                            f"Esperando {tiempo_espera}s antes de reintentar..."
                        )
                    )
                    time.sleep(tiempo_espera)
                    tiempo_espera *= 2  # Backoff exponencial
                else:
                    raise CommandError(
                        f"Error al guardar después de {intento} intentos: {e}"
                    )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("✓ Balance inicial corregido exitosamente")
        )
        self.stdout.write("")
        self.stdout.write("VALORES ACTUALIZADOS:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"balance_meta_base:      US$ {config.balance_meta_base:,.2f}")
        self.stdout.write(f"balance_stop_loss_base: US$ {config.balance_stop_loss_base:,.2f}")
        self.stdout.write(f"meta_actual:            US$ {config.meta_actual:,.2f}")
        self.stdout.write(f"stop_loss_actual:       US$ {config.stop_loss_actual:,.2f}")
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Ejecuta 'python manage.py diagnosticar_balance' para verificar que la discrepancia se ha resuelto."
            )
        )

