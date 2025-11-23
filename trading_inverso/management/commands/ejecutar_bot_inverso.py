"""
Comando para ejecutar el bot inverso.
Este bot monitorea las operaciones del bot principal y ejecuta la dirección opuesta.
"""
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from historial.models import Operacion as OperacionPrincipal

from trading_inverso.services import MotorTradingInverso, GestorBotInverso


class Command(BaseCommand):
    help = "Inicia el loop del bot inverso que ejecuta operaciones opuestas al bot principal."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=int,
            default=5,
            help="Segundos de espera entre cada verificación de operaciones del bot principal.",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        motor = MotorTradingInverso()
        gestor = GestorBotInverso()

        self.stdout.write(self.style.SUCCESS("🤖 Bot Inverso iniciado."))
        self.stdout.write(f"Intervalo de verificación: {intervalo}s")
        self.stdout.write("Monitoreando operaciones del bot principal...")

        # Obtener la última operación del bot principal antes de iniciar
        ultima_operacion_id = None
        ultima_operacion = OperacionPrincipal.objetos.reales().order_by('-hora_inicio').first()
        if ultima_operacion:
            ultima_operacion_id = ultima_operacion.id

        while True:
            try:
                gestor.configuracion.refresh_from_db()
                gestor.sincronizar_balance_desde_api()
                gestor.configuracion.refresh_from_db()

                # Verificar si debe reanudar
                if gestor.configuracion.estado == gestor.configuracion.Estado.PAUSADO:
                    if gestor.configuracion.pausa_finaliza and timezone.now() >= gestor.configuracion.pausa_finaliza:
                        gestor.configuracion.reanudar()
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Bot inverso reanudado."
                            )
                        )

                estado = gestor.obtener_estado()

                if estado.estado == gestor.configuracion.Estado.OPERANDO:
                    # Buscar nuevas operaciones del bot principal
                    operaciones_nuevas = OperacionPrincipal.objetos.reales().filter(
                        id__gt=ultima_operacion_id if ultima_operacion_id else 0
                    ).order_by('id')

                    for operacion_principal in operaciones_nuevas:
                        # Verificar que la operación esté completada (no pendiente)
                        if operacion_principal.resultado == OperacionPrincipal.Resultado.PENDIENTE:
                            continue

                        # Verificar que no sea simulada
                        if operacion_principal.es_simulada:
                            continue

                        self.stdout.write(
                            f"[{timezone.now():%Y-%m-%d %H:%M:%S}] 🔄 Nueva operación principal detectada: "
                            f"{operacion_principal.activo} {operacion_principal.direccion} "
                            f"({operacion_principal.resultado})"
                        )

                        # Ejecutar operación inversa
                        if not estado.en_operacion:
                            operacion_inversa = motor.ejecutar_ciclo_inverso(operacion_principal)
                            if operacion_inversa:
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ✓ Operación INVERSA ejecutada: "
                                        f"{operacion_inversa.numero_contrato} "
                                        f"{operacion_inversa.resultado.upper()} "
                                        f"beneficio={operacion_inversa.beneficio}"
                                    )
                                )
                                ultima_operacion_id = operacion_principal.id
                            else:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ⚠️ No se pudo ejecutar operación inversa."
                                    )
                                )
                        else:
                            self.stdout.write(
                                f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ⏸️  Bot inverso ya tiene una operación en curso, esperando..."
                            )

                    # Actualizar última operación procesada
                    if operaciones_nuevas.exists():
                        ultima_operacion_id = operaciones_nuevas.last().id

                elif estado.estado == gestor.configuracion.Estado.PAUSADO:
                    tiempo_restante = None
                    if estado.pausa_finaliza:
                        tiempo_restante = estado.pausa_finaliza - timezone.now()
                        horas = int(tiempo_restante.total_seconds() / 3600)
                        minutos = int((tiempo_restante.total_seconds() % 3600) / 60)
                        self.stdout.write(
                            f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ⏸️  Bot inverso PAUSADO. "
                            f"Se reactivará en: {horas}h {minutos}m"
                        )
                    else:
                        self.stdout.write(
                            f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ⏸️  Bot inverso PAUSADO."
                        )

                time.sleep(intervalo)

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\n🛑 Bot inverso detenido por el usuario."))
                break
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ❌ Error: {str(e)}"
                    )
                )
                import traceback
                self.stdout.write(traceback.format_exc())
                time.sleep(intervalo)

