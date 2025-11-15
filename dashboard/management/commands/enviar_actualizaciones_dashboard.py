"""
Comando para enviar actualizaciones del dashboard cada 10 segundos.
Este comando debe ejecutarse como un servicio systemd separado.
"""
import time

from django.core.management.base import BaseCommand

from dashboard.services import enviar_actualizacion_dashboard


class Command(BaseCommand):
    help = "Envía actualizaciones del dashboard cada 10 segundos a través de WebSocket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo",
            type=int,
            default=10,
            help="Intervalo en segundos entre actualizaciones (default: 10)",
        )

    def handle(self, *args, **options):
        intervalo = options["intervalo"]
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Iniciando envío de actualizaciones del dashboard cada {intervalo} segundos..."
            )
        )
        
        try:
            while True:
                enviar_actualizacion_dashboard()
                time.sleep(intervalo)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Deteniendo envío de actualizaciones..."))
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Error al enviar actualizaciones: {e}")
            )
            raise

