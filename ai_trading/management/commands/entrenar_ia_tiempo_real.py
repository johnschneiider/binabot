"""
Comando para entrenar la IA observando trades reales en tiempo real.
"""
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from ai_trading.models import EntrenamientoIA, EstrategiaGenetica
from ai_trading.services import ObservadorTradesReales


class Command(BaseCommand):
    help = "Entrena la IA observando trades reales del bot principal en tiempo real"

    def add_arguments(self, parser):
        parser.add_argument(
            '--intervalo',
            type=int,
            default=5,
            help='Intervalo en segundos para verificar nuevos trades (default: 5)',
        )
        parser.add_argument(
            '--nombre',
            type=str,
            default=None,
            help='Nombre del entrenamiento (default: auto-generado)',
        )

    def handle(self, *args, **options):
        intervalo = options['intervalo']
        nombre = options['nombre'] or f"Entrenamiento_TiempoReal_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Verificar que haya estrategias activas
        estrategias_activas = EstrategiaGenetica.objects.filter(activa=True)
        if estrategias_activas.count() == 0:
            self.stdout.write(
                self.style.ERROR(
                    "\n⚠️  No hay estrategias activas. "
                    "Primero crea estrategias con: python manage.py entrenar_ia"
                )
            )
            return
        
        # Crear o obtener entrenamiento
        entrenamiento, creado = EntrenamientoIA.objects.get_or_create(
            nombre=nombre,
            defaults={
                'tipo': 'genetico',
                'estado': EntrenamientoIA.Estado.EN_CURSO,
                'iniciada': timezone.now(),
            }
        )
        
        if not creado:
            entrenamiento.estado = EntrenamientoIA.Estado.EN_CURSO
            entrenamiento.iniciada = timezone.now()
            entrenamiento.save()
        
        self.stdout.write(self.style.SUCCESS(f"\n{'='*80}"))
        self.stdout.write(self.style.SUCCESS("ENTRENAMIENTO DE IA EN TIEMPO REAL"))
        self.stdout.write(self.style.SUCCESS(f"{'='*80}"))
        self.stdout.write(f"Nombre: {nombre}")
        self.stdout.write(f"Intervalo: {intervalo} segundos")
        self.stdout.write(f"Estrategias activas: {estrategias_activas.count()}")
        self.stdout.write(f"\nObservando trades reales del bot principal...")
        self.stdout.write(f"Presiona Ctrl+C para detener\n")
        
        observador = ObservadorTradesReales(entrenamiento)
        total_procesados = 0
        
        try:
            while True:
                trades_procesados = observador.procesar_nuevos_trades()
                total_procesados += trades_procesados
                
                if trades_procesados > 0:
                    self.stdout.write(
                        f"[{timezone.now().strftime('%H:%M:%S')}] "
                        f"Procesados {trades_procesados} trade(s) nuevo(s) "
                        f"(Total: {total_procesados})"
                    )
                    
                    # Mostrar mejor estrategia
                    mejor = EstrategiaGenetica.objects.filter(activa=True).order_by('-fitness').first()
                    if mejor:
                        self.stdout.write(
                            f"  Mejor estrategia: {mejor.nombre} "
                            f"(Fitness: {mejor.fitness:.4f}, "
                            f"Winrate: {mejor.winrate}%, "
                            f"Ops: {mejor.operaciones_evaluadas})"
                        )
                
                time.sleep(intervalo)
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS(f"\n\n{'='*80}"))
            self.stdout.write(self.style.SUCCESS("ENTRENAMIENTO DETENIDO"))
            self.stdout.write(self.style.SUCCESS(f"{'='*80}"))
            self.stdout.write(f"Total trades procesados: {total_procesados}")
            
            entrenamiento.estado = EntrenamientoIA.Estado.COMPLETADO
            entrenamiento.finalizada = timezone.now()
            entrenamiento.duracion_segundos = int(
                (entrenamiento.finalizada - entrenamiento.iniciada).total_seconds()
            )
            entrenamiento.save()
            
            mejor = EstrategiaGenetica.objects.filter(activa=True).order_by('-fitness').first()
            if mejor:
                self.stdout.write(f"\nMejor estrategia final:")
                self.stdout.write(f"  Nombre: {mejor.nombre}")
                self.stdout.write(f"  Fitness: {mejor.fitness:.4f}")
                self.stdout.write(f"  Winrate: {mejor.winrate}%")
                self.stdout.write(f"  Operaciones evaluadas: {mejor.operaciones_evaluadas}")
            
            self.stdout.write("\n")

