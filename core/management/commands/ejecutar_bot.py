import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.services import GestorBotCore
from trading.services import MotorTrading


class Command(BaseCommand):
    help = "Inicia el loop principal del bot sin Celery ni Redis."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=int,
            default=60,
            help="Segundos de espera entre cada ciclo de verificación/operación.",
        )
        parser.add_argument(
            "--intervalo-simulacion",
            type=int,
            default=3600,
            help="Segundos mínimos entre simulaciones mientras el bot está en pausa.",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        intervalo_simulacion = options["intervalo_simulacion"]

        gestor = GestorBotCore()
        motor = MotorTrading()

        self.stdout.write(self.style.SUCCESS("Loop principal del bot iniciado."))
        self.stdout.write(f"Intervalo de ciclo: {intervalo}s")

        while True:
            try:
                gestor.configuracion.refresh_from_db()
                # Sincronizar balance con la API antes de evaluar el estado actual.
                gestor.sincronizar_balance_desde_api()
                gestor.configuracion.refresh_from_db()

                if gestor.debe_reanudar():
                    gestor.reanudar_operativa()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Bot reanudado."
                        )
                    )

                estado = gestor.obtener_estado()

                if estado.estado == gestor.configuracion.Estado.OPERANDO:
                    operacion = motor.ejecutar_ciclo()
                    if operacion:
                        self.stdout.write(
                            f"[{timezone.now():%Y-%m-%d %H:%M:%S}] "
                            f"Operación {operacion.numero_contrato} "
                            f"{operacion.resultado.upper()} "
                            f"beneficio={operacion.beneficio}"
                        )
                else:
                    self.stdout.write(
                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Bot en pausa. "
                        "Esperando reanudación automática."
                    )
                    resultado = gestor.ejecutar_simulacion_pausa(intervalo_simulacion)
                    if resultado:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[{timezone.now():%Y-%m-%d %H:%M:%S}] "
                                f"Simulación actualizada. Mejor horario {resultado.hora.strftime('%H:%M')} "
                                f"(winrate {resultado.winrate}%)."
                            )
                        )

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Loop detenido por el usuario."))
                break
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Error en el loop: {exc}"
                    )
                )

            time.sleep(intervalo)

