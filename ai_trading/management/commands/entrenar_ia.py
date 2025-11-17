"""
Comando para entrenar la IA con algoritmo genético.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from ai_trading.genetico import AlgoritmoGenetico


class Command(BaseCommand):
    help = "Entrena la IA usando algoritmo genético sobre datos históricos"

    def add_arguments(self, parser):
        parser.add_argument(
            '--generaciones',
            type=int,
            default=50,
            help='Número de generaciones a evolucionar (default: 50)',
        )
        parser.add_argument(
            '--poblacion',
            type=int,
            default=50,
            help='Tamaño de la población (default: 50)',
        )
        parser.add_argument(
            '--mutacion',
            type=float,
            default=0.10,
            help='Tasa de mutación (0.0-1.0, default: 0.10)',
        )
        parser.add_argument(
            '--crossover',
            type=float,
            default=0.80,
            help='Tasa de crossover (0.0-1.0, default: 0.80)',
        )
        parser.add_argument(
            '--elite',
            type=int,
            default=5,
            help='Tamaño de la elite (default: 5)',
        )
        parser.add_argument(
            '--dias-datos',
            type=int,
            default=7,
            help='Días de datos históricos a usar (default: 7)',
        )
        parser.add_argument(
            '--nombre',
            type=str,
            default=None,
            help='Nombre del entrenamiento (default: auto-generado)',
        )

    def handle(self, *args, **options):
        generaciones = options['generaciones']
        tamano_poblacion = options['poblacion']
        tasa_mutacion = Decimal(str(options['mutacion']))
        tasa_crossover = Decimal(str(options['crossover']))
        elite_size = options['elite']
        dias_datos = options['dias_datos']
        nombre = options['nombre'] or f"Entrenamiento_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        
        datos_desde = timezone.now() - timedelta(days=dias_datos)
        datos_hasta = timezone.now()
        
        self.stdout.write(self.style.SUCCESS(f"\n{'='*80}"))
        self.stdout.write(self.style.SUCCESS(f"INICIANDO ENTRENAMIENTO DE IA"))
        self.stdout.write(self.style.SUCCESS(f"{'='*80}"))
        self.stdout.write(f"Nombre: {nombre}")
        self.stdout.write(f"Generaciones: {generaciones}")
        self.stdout.write(f"Tamaño población: {tamano_poblacion}")
        self.stdout.write(f"Tasa mutación: {tasa_mutacion}")
        self.stdout.write(f"Tasa crossover: {tasa_crossover}")
        self.stdout.write(f"Elite size: {elite_size}")
        self.stdout.write(f"Datos desde: {datos_desde}")
        self.stdout.write(f"Datos hasta: {datos_hasta}")
        self.stdout.write(f"\n{'='*80}\n")
        
        # Crear algoritmo genético
        algoritmo = AlgoritmoGenetico(
            tamano_poblacion=tamano_poblacion,
            tasa_mutacion=tasa_mutacion,
            tasa_crossover=tasa_crossover,
            elite_size=elite_size,
            datos_desde=datos_desde,
            datos_hasta=datos_hasta,
        )
        
        # Callback de progreso
        def callback_progreso(gen, total, poblacion, mejor_estrategia):
            self.stdout.write(
                f"[Gen {gen+1}/{total}] "
                f"Fitness promedio: {poblacion.fitness_promedio:.4f} | "
                f"Mejor: {poblacion.fitness_mejor:.4f} | "
                f"Peor: {poblacion.fitness_peor:.4f}"
            )
            if mejor_estrategia:
                self.stdout.write(
                    f"  Mejor estrategia: {mejor_estrategia.nombre} "
                    f"(Fitness: {mejor_estrategia.fitness:.4f})"
                )
        
        # Entrenar
        try:
            entrenamiento = algoritmo.entrenar(
                generaciones=generaciones,
                nombre_entrenamiento=nombre,
                callback_progreso=callback_progreso,
            )
            
            self.stdout.write(self.style.SUCCESS(f"\n{'='*80}"))
            self.stdout.write(self.style.SUCCESS("ENTRENAMIENTO COMPLETADO"))
            self.stdout.write(self.style.SUCCESS(f"{'='*80}"))
            self.stdout.write(f"Estado: {entrenamiento.get_estado_display()}")
            self.stdout.write(f"Duración: {entrenamiento.duracion_segundos} segundos")
            
            if entrenamiento.mejor_estrategia:
                mejor = entrenamiento.mejor_estrategia
                self.stdout.write(f"\nMejor estrategia encontrada:")
                self.stdout.write(f"  ID: {mejor.id}")
                self.stdout.write(f"  Nombre: {mejor.nombre}")
                self.stdout.write(f"  Fitness: {mejor.fitness:.4f}")
                self.stdout.write(f"  Winrate: {mejor.winrate}%")
                self.stdout.write(f"  Beneficio total: ${mejor.beneficio_total}")
                self.stdout.write(f"\nParámetros:")
                self.stdout.write(f"  Umbral variación min: {mejor.umbral_variacion_min}")
                self.stdout.write(f"  Umbral confianza min: {mejor.umbral_confianza_min}")
                self.stdout.write(f"  Ventana ticks: {mejor.ventana_ticks}")
                self.stdout.write(f"  Peso winrate simulación: {mejor.peso_winrate_simulacion}")
                self.stdout.write(f"  Peso confianza horario: {mejor.peso_confianza_horario}")
                self.stdout.write(f"  Umbral riesgo max: {mejor.umbral_riesgo_max}")
            
            self.stdout.write("\n")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nError durante el entrenamiento: {e}"))
            import traceback
            self.stdout.write(self.style.ERROR(traceback.format_exc()))
            raise

