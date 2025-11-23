"""
Comando para enviar actualizaciones del bot inverso en tiempo real.
Se ejecuta periódicamente para mantener el dashboard actualizado.
"""
import time
from django.core.management.base import BaseCommand
from trading_inverso.services_websocket import enviar_actualizacion_bot_inverso


class Command(BaseCommand):
    help = "Envía actualizaciones del bot inverso en tiempo real a través de WebSocket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=int,
            default=10,
            help="Segundos entre cada actualización. Por defecto: 10s",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        
        self.stdout.write(
            self.style.SUCCESS(f"Enviando actualizaciones del bot inverso cada {intervalo}s")
        )

        while True:
            try:
                enviar_actualizacion_bot_inverso()
                time.sleep(intervalo)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\n🛑 Deteniendo envío de actualizaciones."))
                break
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error enviando actualizaciones: {e}")
                )
                time.sleep(intervalo)

