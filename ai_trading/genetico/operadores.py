"""
Operadores genéticos: mutación, crossover y selección.
"""
import random
from decimal import Decimal
from typing import List, Tuple
from ai_trading.models import EstrategiaGenetica


class OperadorMutacion:
    """
    Aplica mutación a una estrategia genética.
    """
    
    def __init__(self, tasa_mutacion: Decimal = Decimal("0.10")):
        self.tasa_mutacion = tasa_mutacion
    
    def mutar(self, estrategia: EstrategiaGenetica) -> EstrategiaGenetica:
        """
        Crea una copia mutada de la estrategia.
        """
        from django.utils import timezone
        nueva = EstrategiaGenetica()
        timestamp = int(timezone.now().timestamp() * 1000)
        nueva.nombre = f"{estrategia.nombre}_mut_{timestamp}_{random.randint(1000, 9999)}"
        nueva.generacion = estrategia.generacion + 1
        
        # Copiar todos los parámetros
        nueva.umbral_variacion_min = estrategia.umbral_variacion_min
        nueva.umbral_confianza_min = estrategia.umbral_confianza_min
        nueva.ventana_ticks = estrategia.ventana_ticks
        nueva.peso_winrate_simulacion = estrategia.peso_winrate_simulacion
        nueva.peso_confianza_horario = estrategia.peso_confianza_horario
        nueva.umbral_riesgo_max = estrategia.umbral_riesgo_max
        
        # Aplicar mutación aleatoria a cada parámetro
        if random.random() < float(self.tasa_mutacion):
            # Mutar umbral_variacion_min (±20%)
            variacion = Decimal(str(random.uniform(-0.20, 0.20)))
            nueva.umbral_variacion_min = max(
                Decimal("0.01"),
                min(Decimal("10.00"), estrategia.umbral_variacion_min * (Decimal("1.00") + variacion))
            )
        
        if random.random() < float(self.tasa_mutacion):
            # Mutar umbral_confianza_min (±20%)
            variacion = Decimal(str(random.uniform(-0.20, 0.20)))
            nueva.umbral_confianza_min = max(
                Decimal("0.01"),
                min(Decimal("99.99"), estrategia.umbral_confianza_min * (Decimal("1.00") + variacion))
            )
        
        if random.random() < float(self.tasa_mutacion):
            # Mutar ventana_ticks (±2 ticks)
            nueva.ventana_ticks = max(
                1,
                min(100, estrategia.ventana_ticks + random.randint(-2, 2))
            )
        
        if random.random() < float(self.tasa_mutacion):
            # Mutar pesos (±10%)
            variacion = Decimal(str(random.uniform(-0.10, 0.10)))
            nueva.peso_winrate_simulacion = max(
                Decimal("0.00"),
                min(Decimal("1.00"), estrategia.peso_winrate_simulacion * (Decimal("1.00") + variacion))
            )
        
        if random.random() < float(self.tasa_mutacion):
            variacion = Decimal(str(random.uniform(-0.10, 0.10)))
            nueva.peso_confianza_horario = max(
                Decimal("0.00"),
                min(Decimal("1.00"), estrategia.peso_confianza_horario * (Decimal("1.00") + variacion))
            )
        
        return nueva


class OperadorCrossover:
    """
    Aplica crossover (reproducción) entre dos estrategias.
    """
    
    def cruzar(
        self,
        padre1: EstrategiaGenetica,
        padre2: EstrategiaGenetica,
    ) -> Tuple[EstrategiaGenetica, EstrategiaGenetica]:
        """
        Cruza dos estrategias para crear dos hijos.
        """
        from django.utils import timezone
        hijo1 = EstrategiaGenetica()
        hijo2 = EstrategiaGenetica()
        
        timestamp = int(timezone.now().timestamp() * 1000)
        hijo1.nombre = f"hijo1_{timestamp}_{random.randint(1000, 9999)}"
        hijo2.nombre = f"hijo2_{timestamp}_{random.randint(1000, 9999)}"
        hijo1.generacion = max(padre1.generacion, padre2.generacion) + 1
        hijo2.generacion = max(padre1.generacion, padre2.generacion) + 1
        
        # Crossover uniforme: cada gen viene de uno u otro padre aleatoriamente
        if random.random() < 0.5:
            hijo1.umbral_variacion_min = padre1.umbral_variacion_min
            hijo2.umbral_variacion_min = padre2.umbral_variacion_min
        else:
            hijo1.umbral_variacion_min = padre2.umbral_variacion_min
            hijo2.umbral_variacion_min = padre1.umbral_variacion_min
        
        if random.random() < 0.5:
            hijo1.umbral_confianza_min = padre1.umbral_confianza_min
            hijo2.umbral_confianza_min = padre2.umbral_confianza_min
        else:
            hijo1.umbral_confianza_min = padre2.umbral_confianza_min
            hijo2.umbral_confianza_min = padre1.umbral_confianza_min
        
        if random.random() < 0.5:
            hijo1.ventana_ticks = padre1.ventana_ticks
            hijo2.ventana_ticks = padre2.ventana_ticks
        else:
            hijo1.ventana_ticks = padre2.ventana_ticks
            hijo2.ventana_ticks = padre1.ventana_ticks
        
        # Promedio para pesos (crossover aritmético)
        hijo1.peso_winrate_simulacion = (padre1.peso_winrate_simulacion + padre2.peso_winrate_simulacion) / Decimal("2.00")
        hijo2.peso_winrate_simulacion = (padre1.peso_winrate_simulacion + padre2.peso_winrate_simulacion) / Decimal("2.00")
        
        hijo1.peso_confianza_horario = (padre1.peso_confianza_horario + padre2.peso_confianza_horario) / Decimal("2.00")
        hijo2.peso_confianza_horario = (padre1.peso_confianza_horario + padre2.peso_confianza_horario) / Decimal("2.00")
        
        if random.random() < 0.5:
            hijo1.umbral_riesgo_max = padre1.umbral_riesgo_max
            hijo2.umbral_riesgo_max = padre2.umbral_riesgo_max
        else:
            hijo1.umbral_riesgo_max = padre2.umbral_riesgo_max
            hijo2.umbral_riesgo_max = padre1.umbral_riesgo_max
        
        return hijo1, hijo2


class OperadorSeleccion:
    """
    Selecciona estrategias para reproducción basado en fitness.
    """
    
    def seleccionar_torneo(
        self,
        poblacion: List[EstrategiaGenetica],
        tamano_torneo: int = 3,
    ) -> EstrategiaGenetica:
        """
        Selección por torneo: elige k estrategias aleatorias y retorna la mejor.
        """
        torneo = random.sample(poblacion, min(tamano_torneo, len(poblacion)))
        return max(torneo, key=lambda e: e.fitness)
    
    def seleccionar_ruleta(
        self,
        poblacion: List[EstrategiaGenetica],
    ) -> EstrategiaGenetica:
        """
        Selección por ruleta: probabilidad proporcional al fitness.
        """
        # Normalizar fitness a valores positivos
        fitness_min = min(e.fitness for e in poblacion)
        fitness_ajustados = [e.fitness - fitness_min + Decimal("0.0001") for e in poblacion]
        total = sum(fitness_ajustados)
        
        if total == Decimal("0.00"):
            return random.choice(poblacion)
        
        # Selección aleatoria ponderada
        r = random.uniform(0, float(total))
        acumulado = Decimal("0.00")
        
        for estrategia, fitness_ajustado in zip(poblacion, fitness_ajustados):
            acumulado += fitness_ajustado
            if acumulado >= Decimal(str(r)):
                return estrategia
        
        return poblacion[-1]  # Fallback

