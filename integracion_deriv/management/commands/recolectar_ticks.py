import asyncio

from django.core.management.base import BaseCommand, CommandError

from core.models import ActivoPermitido
from integracion_deriv.services import TickStreamRecorder


class Command(BaseCommand):
    help = "Suscribe al flujo de ticks de Deriv y los guarda en la base de datos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--activos",
            nargs="*",
            help=(
                "Símbolos de los activos a suscribir (por ejemplo, R_100 R_50). "
                "Si se omite, se usarán todos los activos habilitados en el administrador."
            ),
        )
        parser.add_argument(
            "--duracion",
            type=int,
            default=0,
            help="Segundos a escuchar el flujo. 0 para indefinido.",
        )
        parser.add_argument(
            "--max-ticks",
            type=int,
            default=0,
            help="Número máximo de ticks a guardar antes de cerrar. 0 para ilimitado.",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Si se indica, reinicia automáticamente la recolección al terminar (ideal para ejecución continua).",
        )

    def handle(self, *args, **options):
        activos = options.get("activos") or list(
            ActivoPermitido.objects.filter(habilitado=True).values_list("nombre", flat=True)
        )
        if not activos:
            raise CommandError(
                "No se especificaron activos y no hay activos habilitados en el sistema."
            )

        duracion = options["duracion"] or None
        max_ticks = options["max_ticks"] or None
        loop = options["loop"]

        ciclo = 1
        while True:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[ciclo #{ciclo}] Iniciando recolección de ticks para {', '.join(activos)} "
                    f"(duración={'∞' if duracion is None else duracion}s, "
                    f"máx. ticks={'∞' if max_ticks is None else max_ticks})"
                )
            )
            recorder = TickStreamRecorder(
                activos=activos, duracion=duracion, max_ticks=max_ticks
            )
            try:
                resultado = asyncio.run(recorder.ejecutar())
            except KeyboardInterrupt:
                self.stdout.write(
                    self.style.WARNING("Recolección interrumpida por el usuario.")
                )
                break
            except Exception as exc:
                raise CommandError(f"Error durante la recolección de ticks: {exc}") from exc
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[ciclo #{ciclo}] Finalizado. Ticks guardados: {resultado.total_ticks} "
                        f"({', '.join(f'{simbolo}: {cantidad}' for simbolo, cantidad in resultado.ticks_por_activo.items())})."
                    )
                )

            if not loop:
                break
            ciclo += 1

