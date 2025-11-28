"""
Comando para ejecutar el bot inverso.
Este bot usa la misma estrategia EMA que el bot principal pero con dirección invertida.
Opera de forma independiente, no solo reaccionando a operaciones del bot principal.
"""
import time
from django.core.management.base import BaseCommand
from django.utils import timezone

from trading_inverso.services import MotorTradingInverso, GestorBotInverso


class Command(BaseCommand):
    help = "Inicia el loop del bot inverso usando estrategia EMA (dirección invertida)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=int,
            default=60,
            help="Segundos de espera entre cada ciclo de evaluación/operación.",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        motor = MotorTradingInverso()
        gestor = GestorBotInverso()

        self.stdout.write(self.style.SUCCESS("🤖 Bot Inverso iniciado (Estrategia EMA inversa)."))
        self.stdout.write(f"Intervalo de ciclo: {intervalo}s")
        self.stdout.write("Operando de forma independiente con EMAs (dirección invertida)...")

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
                    # Log detallado del estado antes de ejecutar
                    self.stdout.write(
                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Estado: OPERANDO | "
                        f"en_operacion={estado.en_operacion} | "
                        f"balance={estado.balance_actual}"
                    )
                    
                    if estado.en_operacion:
                        self.stdout.write(
                            f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ⏸️  Bot inverso ya tiene una operación en curso, esperando..."
                        )
                    else:
                        # Ejecutar ciclo con estrategia EMA (dirección invertida)
                        operacion = motor.ejecutar_ciclo_ema()
                        if operacion:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ✓ Operación INVERSA {operacion.numero_contrato} "
                                    f"{operacion.resultado.upper()} "
                                    f"beneficio={operacion.beneficio}"
                                )
                            )
                        else:
                            # Log cuando no se ejecuta operación para diagnóstico
                            mensaje_extra = ""
                            if hasattr(motor, 'ultimo_mensaje_diagnostico') and motor.ultimo_mensaje_diagnostico:
                                mensaje_extra = f" | {motor.ultimo_mensaje_diagnostico}"
                            self.stdout.write(
                                f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ⚠️  Ciclo ejecutado pero no se generó operación inversa{mensaje_extra}"
                            )
                else:
                    self.stdout.write(
                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Bot inverso en pausa (estado: {estado.estado}). "
                        "Esperando reanudación automática."
                    )
                    
                    if estado.pausa_finaliza:
                        tiempo_restante = estado.pausa_finaliza - timezone.now()
                        if tiempo_restante.total_seconds() > 0:
                            horas = int(tiempo_restante.total_seconds() / 3600)
                            minutos = int((tiempo_restante.total_seconds() % 3600) / 60)
                            self.stdout.write(
                                f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Se reactivará en: {horas}h {minutos}m"
                            )

                time.sleep(intervalo)

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\n🛑 Bot inverso detenido por el usuario."))
                break
            except Exception as e:
                import traceback
                error_traceback = traceback.format_exc()
                self.stderr.write(
                    self.style.ERROR(
                        f"[{timezone.now():%Y-%m-%d %H:%M:%S}] ❌ Error en el loop: {e}"
                    )
                )
                self.stderr.write(
                    self.style.ERROR(
                        f"Traceback completo:\n{error_traceback}"
                    )
                )
                self.stdout.write(
                    f"[{timezone.now():%Y-%m-%d %H:%M:%S}] Continuando el loop después del error..."
                )
                time.sleep(intervalo)

