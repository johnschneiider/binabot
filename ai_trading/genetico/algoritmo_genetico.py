"""
Algoritmo genético principal para optimizar estrategias de trading.
"""
import random
from decimal import Decimal
from typing import List, Optional, Callable
from django.utils import timezone
from ai_trading.models import EstrategiaGenetica, PoblacionGenetica, EntrenamientoIA
from .fitness import CalculadorFitness
from .operadores import OperadorMutacion, OperadorCrossover, OperadorSeleccion


class AlgoritmoGenetico:
    """
    Implementa un algoritmo genético para evolucionar estrategias de trading.
    """
    
    def __init__(
        self,
        tamano_poblacion: int = 50,
        tasa_mutacion: Decimal = Decimal("0.10"),
        tasa_crossover: Decimal = Decimal("0.80"),
        elite_size: int = 5,
        datos_desde=None,
        datos_hasta=None,
        activos=None,
    ):
        self.tamano_poblacion = tamano_poblacion
        self.tasa_mutacion = tasa_mutacion
        self.tasa_crossover = tasa_crossover
        self.elite_size = elite_size
        
        self.calculador_fitness = CalculadorFitness(
            datos_desde=datos_desde,
            datos_hasta=datos_hasta,
            activos=activos,
        )
        
        self.operador_mutacion = OperadorMutacion(tasa_mutacion=tasa_mutacion)
        self.operador_crossover = OperadorCrossover()
        self.operador_seleccion = OperadorSeleccion()
    
    def crear_poblacion_inicial(self, nombre: str = "Población Inicial") -> PoblacionGenetica:
        """
        Crea una población inicial de estrategias aleatorias.
        """
        poblacion = PoblacionGenetica.objects.create(
            nombre=nombre,
            generacion=0,
            tamano_poblacion=self.tamano_poblacion,
            tasa_mutacion=self.tasa_mutacion,
            tasa_crossover=self.tasa_crossover,
            elite_size=self.elite_size,
        )
        
        estrategias = []
        timestamp = int(timezone.now().timestamp() * 1000)  # Timestamp en milisegundos para unicidad
        for i in range(self.tamano_poblacion):
            estrategia = EstrategiaGenetica.objects.create(
                nombre=f"Estrategia_Gen0_{timestamp}_{i+1}",
                generacion=0,
                # Parámetros aleatorios iniciales
                umbral_variacion_min=Decimal(str(random.uniform(0.01, 2.00))).quantize(Decimal("0.01")),
                umbral_confianza_min=Decimal(str(random.uniform(0.10, 5.00))).quantize(Decimal("0.01")),
                ventana_ticks=random.randint(2, 20),
                peso_winrate_simulacion=Decimal(str(random.uniform(0.0, 1.0))).quantize(Decimal("0.01")),
                peso_confianza_horario=Decimal(str(random.uniform(0.0, 1.0))).quantize(Decimal("0.01")),
                umbral_riesgo_max=Decimal(str(random.uniform(1.0, 5.0))).quantize(Decimal("0.01")),
            )
            estrategias.append(estrategia)
        
        poblacion.estrategias.set(estrategias)
        return poblacion
    
    def evaluar_poblacion(self, poblacion: PoblacionGenetica, callback_progreso=None) -> None:
        """
        Evalúa todas las estrategias de una población y actualiza su fitness.
        """
        estrategias = list(poblacion.estrategias.all())
        total = len(estrategias)
        
        for idx, estrategia in enumerate(estrategias, 1):
            if callback_progreso:
                callback_progreso(f"Evaluando estrategia {idx}/{total}: {estrategia.nombre}")
            else:
                print(f"  Evaluando estrategia {idx}/{total}: {estrategia.nombre}", file=sys.stderr)
                sys.stderr.flush()
            
            fitness = self.calculador_fitness.calcular_fitness(estrategia)
            estrategia.fitness = fitness
            estrategia.ultima_evaluacion = timezone.now()
            estrategia.save(update_fields=["fitness", "ultima_evaluacion", "actualizada"])
            
            if callback_progreso:
                callback_progreso(f"  ✓ Fitness: {fitness:.4f}")
            else:
                print(f"    ✓ Fitness: {fitness:.4f}", file=sys.stderr)
                sys.stderr.flush()
            
            # Enviar actualización WebSocket
            try:
                from ai_trading.services_websocket import enviar_evaluacion_estrategia
                enviar_evaluacion_estrategia(
                    estrategia_numero=idx,
                    total_estrategias=total,
                    estrategia_nombre=estrategia.nombre,
                    fitness=fitness,
                )
            except Exception:
                # Si falla el WebSocket, no interrumpir el entrenamiento
                pass
        
        # Actualizar métricas de la población
        fitness_values = [e.fitness for e in estrategias]
        poblacion.fitness_promedio = sum(fitness_values) / len(fitness_values) if fitness_values else Decimal("0.00")
        poblacion.fitness_mejor = max(fitness_values) if fitness_values else Decimal("0.00")
        poblacion.fitness_peor = min(fitness_values) if fitness_values else Decimal("0.00")
        poblacion.save(update_fields=["fitness_promedio", "fitness_mejor", "fitness_peor", "actualizada"])
    
    def evolucionar(self, poblacion_actual: PoblacionGenetica) -> PoblacionGenetica:
        """
        Evoluciona una población creando una nueva generación.
        """
        estrategias_actuales = list(poblacion_actual.estrategias.all())
        estrategias_actuales.sort(key=lambda e: e.fitness, reverse=True)
        
        # Crear nueva población
        nueva_poblacion = PoblacionGenetica.objects.create(
            nombre=poblacion_actual.nombre,
            generacion=poblacion_actual.generacion + 1,
            tamano_poblacion=self.tamano_poblacion,
            tasa_mutacion=self.tasa_mutacion,
            tasa_crossover=self.tasa_crossover,
            elite_size=self.elite_size,
        )
        
        nuevas_estrategias = []
        
        # Elitismo: las mejores estrategias pasan directamente
        elite = estrategias_actuales[:self.elite_size]
        timestamp = int(timezone.now().timestamp() * 1000)
        for idx, estrategia_elite in enumerate(elite):
            nueva_estrategia = EstrategiaGenetica.objects.create(
                nombre=f"{estrategia_elite.nombre}_elite_{timestamp}_{idx}",
                generacion=nueva_poblacion.generacion,
                umbral_variacion_min=estrategia_elite.umbral_variacion_min,
                umbral_confianza_min=estrategia_elite.umbral_confianza_min,
                ventana_ticks=estrategia_elite.ventana_ticks,
                peso_winrate_simulacion=estrategia_elite.peso_winrate_simulacion,
                peso_confianza_horario=estrategia_elite.peso_confianza_horario,
                umbral_riesgo_max=estrategia_elite.umbral_riesgo_max,
                fitness=estrategia_elite.fitness,
            )
            nuevas_estrategias.append(nueva_estrategia)
        
        # Generar el resto de la población mediante crossover y mutación
        while len(nuevas_estrategias) < self.tamano_poblacion:
            # Crossover
            if random.random() < float(self.tasa_crossover) and len(estrategias_actuales) >= 2:
                padre1 = self.operador_seleccion.seleccionar_torneo(estrategias_actuales)
                padre2 = self.operador_seleccion.seleccionar_torneo(estrategias_actuales)
                
                hijo1, hijo2 = self.operador_crossover.cruzar(padre1, padre2)
                nuevas_estrategias.append(hijo1)
                if len(nuevas_estrategias) < self.tamano_poblacion:
                    nuevas_estrategias.append(hijo2)
            
            # Mutación
            if len(nuevas_estrategias) < self.tamano_poblacion:
                padre = self.operador_seleccion.seleccionar_torneo(estrategias_actuales)
                hijo = self.operador_mutacion.mutar(padre)
                nuevas_estrategias.append(hijo)
        
        # Guardar todas las estrategias
        for estrategia in nuevas_estrategias[:self.tamano_poblacion]:
            estrategia.save()
        
        nueva_poblacion.estrategias.set(nuevas_estrategias[:self.tamano_poblacion])
        return nueva_poblacion
    
    def entrenar(
        self,
        generaciones: int = 50,
        nombre_entrenamiento: str = "Entrenamiento Genético",
        callback_progreso: Optional[Callable] = None,
    ) -> EntrenamientoIA:
        """
        Ejecuta el entrenamiento completo del algoritmo genético.
        """
        entrenamiento = EntrenamientoIA.objects.create(
            nombre=nombre_entrenamiento,
            tipo="genetico",
            estado=EntrenamientoIA.Estado.EN_CURSO,
            generaciones=generaciones,
            tamano_poblacion=self.tamano_poblacion,
            iniciada=timezone.now(),
        )
        
        # Crear población inicial
        poblacion = self.crear_poblacion_inicial(nombre=f"{nombre_entrenamiento}_Gen0")
        entrenamiento.progreso = {"generaciones": []}
        
        try:
            for gen in range(generaciones):
                # Evaluar población actual
                if callback_progreso:
                    callback_progreso(f"\n{'='*80}")
                    callback_progreso(f"EVALUANDO GENERACIÓN {gen+1}/{generaciones}")
                    callback_progreso(f"{'='*80}")
                else:
                    print(f"\n{'='*80}", file=sys.stderr)
                    print(f"EVALUANDO GENERACIÓN {gen+1}/{generaciones}", file=sys.stderr)
                    print(f"{'='*80}", file=sys.stderr)
                    sys.stderr.flush()
                
                self.evaluar_poblacion(poblacion, callback_progreso=callback_progreso)
                
                # Obtener mejor estrategia
                mejor_estrategia = poblacion.estrategias.order_by('-fitness').first()
                
                # Guardar progreso
                progreso_gen = {
                    "generacion": gen,
                    "fitness_promedio": float(poblacion.fitness_promedio),
                    "fitness_mejor": float(poblacion.fitness_mejor),
                    "fitness_peor": float(poblacion.fitness_peor),
                    "mejor_estrategia_id": mejor_estrategia.id if mejor_estrategia else None,
                }
                entrenamiento.progreso["generaciones"].append(progreso_gen)
                entrenamiento.save(update_fields=["progreso", "actualizada"])
                
                # Callback de progreso (pasar tupla para resumen de generación)
                if callback_progreso:
                    callback_progreso((gen, generaciones, poblacion, mejor_estrategia))
                
                # Enviar actualización WebSocket de progreso de generación
                try:
                    from django.utils import timezone
                    from ai_trading.services_websocket import enviar_progreso_generacion
                    ahora = timezone.now()
                    tiempo_transcurrido = (ahora - entrenamiento.iniciada).total_seconds() if entrenamiento.iniciada else 0
                    enviar_progreso_generacion(
                        generacion=gen + 1,
                        total_generaciones=generaciones,
                        fitness_promedio=poblacion.fitness_promedio,
                        fitness_mejor=poblacion.fitness_mejor,
                        fitness_peor=poblacion.fitness_peor,
                        mejor_estrategia_nombre=mejor_estrategia.nombre if mejor_estrategia else "N/A",
                        mejor_estrategia_fitness=mejor_estrategia.fitness if mejor_estrategia else Decimal("0.00"),
                        tiempo_transcurrido=tiempo_transcurrido,
                    )
                except Exception:
                    # Si falla el WebSocket, no interrumpir el entrenamiento
                    pass
                
                # Evolucionar (excepto en la última generación)
                if gen < generaciones - 1:
                    poblacion = self.evolucionar(poblacion)
            
            # Finalizar entrenamiento
            mejor_estrategia = poblacion.estrategias.order_by('-fitness').first()
            entrenamiento.mejor_estrategia = mejor_estrategia
            entrenamiento.fitness_final = mejor_estrategia.fitness if mejor_estrategia else Decimal("0.00")
            entrenamiento.estado = EntrenamientoIA.Estado.COMPLETADO
            entrenamiento.finalizada = timezone.now()
            entrenamiento.duracion_segundos = int((entrenamiento.finalizada - entrenamiento.iniciada).total_seconds())
            entrenamiento.save()
            
        except Exception as e:
            entrenamiento.estado = EntrenamientoIA.Estado.ERROR
            entrenamiento.error_mensaje = str(e)
            entrenamiento.finalizada = timezone.now()
            entrenamiento.save()
            raise
        
        return entrenamiento
