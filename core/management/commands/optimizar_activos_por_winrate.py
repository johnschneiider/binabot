from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from decimal import Decimal

from core.models import ActivoPermitido
from historial.models import Operacion


class Command(BaseCommand):
    help = "Optimiza los activos habilitados basándose en el winrate real de operaciones"

    def add_arguments(self, parser):
        parser.add_argument(
            '--umbral-minimo',
            type=float,
            default=40.0,
            help='Winrate mínimo para mantener un activo habilitado (por defecto: 40.0%%)',
        )
        parser.add_argument(
            '--min-operaciones',
            type=int,
            default=5,
            help='Número mínimo de operaciones para considerar un activo (por defecto: 5)',
        )

    def handle(self, *args, **options):
        umbral_minimo = options['umbral_minimo']
        min_operaciones = options['min_operaciones']

        self.stdout.write("=" * 80)
        self.stdout.write("OPTIMIZACIÓN DE ACTIVOS POR WINRATE")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Umbral mínimo de winrate: {umbral_minimo}%")
        self.stdout.write(f"Mínimo de operaciones: {min_operaciones}")
        self.stdout.write("")

        # Calcular winrate por activo
        operaciones = Operacion.objetos.reales().values('activo')
        estadisticas = operaciones.annotate(
            total=Count('id'),
            ganadas=Count('id', filter=Q(resultado=Operacion.Resultado.GANADA)),
            perdidas=Count('id', filter=Q(resultado=Operacion.Resultado.PERDIDA))
        ).filter(total__gte=min_operaciones).order_by('-total')

        self.stdout.write("Estadísticas por activo:")
        self.stdout.write("-" * 80)

        activos_a_habilitar = []
        activos_a_deshabilitar = []

        for stat in estadisticas:
            total = stat['total']
            ganadas = stat['ganadas']
            perdidas = stat['perdidas']
            winrate = (ganadas / total * 100) if total > 0 else 0
            activo_nombre = stat['activo']

            estado = "[OK] BUENO" if winrate >= umbral_minimo else "[MALO]"
            self.stdout.write(
                f"{estado} {activo_nombre:20s} | "
                f"Ops: {total:3d} | "
                f"G: {ganadas:2d} P: {perdidas:2d} | "
                f"Winrate: {winrate:5.2f}%%"
            )

            if winrate >= umbral_minimo:
                activos_a_habilitar.append(activo_nombre)
            else:
                activos_a_deshabilitar.append(activo_nombre)

        # Activos sin estadísticas suficientes
        todos_activos = set(ActivoPermitido.objects.values_list('nombre', flat=True))
        activos_con_stats = set(stat['activo'] for stat in estadisticas)
        activos_sin_stats = todos_activos - activos_con_stats

        self.stdout.write("")
        self.stdout.write("Activos sin estadísticas suficientes (se mantendrán habilitados):")
        for activo in sorted(activos_sin_stats):
            self.stdout.write(f"  {activo}")

        # Aplicar cambios
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("APLICANDO CAMBIOS")
        self.stdout.write("=" * 80)

        # Habilitar activos con buen winrate
        habilitados = 0
        for nombre in activos_a_habilitar:
            activo, created = ActivoPermitido.objects.get_or_create(nombre=nombre)
            if not activo.habilitado:
                activo.habilitado = True
                activo.save()
                habilitados += 1
                self.stdout.write(self.style.SUCCESS(f"[OK] Habilitado: {nombre}"))

        # Deshabilitar activos con mal winrate
        deshabilitados = 0
        for nombre in activos_a_deshabilitar:
            try:
                activo = ActivoPermitido.objects.get(nombre=nombre)
                if activo.habilitado:
                    activo.habilitado = False
                    activo.save()
                    deshabilitados += 1
                    self.stdout.write(self.style.WARNING(f"[DESHABILITADO] {nombre}"))
            except ActivoPermitido.DoesNotExist:
                pass

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("RESUMEN")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Activos habilitados: {habilitados}")
        self.stdout.write(f"Activos deshabilitados: {deshabilitados}")

        total_habilitados = ActivoPermitido.objects.filter(habilitado=True).count()
        self.stdout.write(f"Total de activos habilitados ahora: {total_habilitados}")
        self.stdout.write("")

