"""
Calculador de fitness para estrategias genéticas.
El fitness determina qué tan buena es una estrategia.
"""
from decimal import Decimal
from typing import List, Dict
from django.utils import timezone
from historial.models import Operacion, Tick
from core.models import ActivoPermitido
from .simulador import SimuladorEstrategia


class CalculadorFitness:
    """
    Calcula el fitness de una estrategia genética basado en:
    - Winrate
    - Beneficio total
    - Ratio de Sharpe (riesgo/retorno)
    - Consistencia
    - Drawdown máximo
    """
    
    def __init__(
        self,
        datos_desde=None,
        datos_hasta=None,
        activos=None,
        peso_winrate=Decimal("0.40"),
        peso_beneficio=Decimal("0.30"),
        peso_sharpe=Decimal("0.20"),
        peso_consistencia=Decimal("0.10"),
    ):
        self.datos_desde = datos_desde or timezone.now() - timezone.timedelta(days=7)
        self.datos_hasta = datos_hasta or timezone.now()
        self.activos = activos or list(ActivoPermitido.objects.filter(habilitado=True).values_list('nombre', flat=True))
        
        # Pesos para calcular fitness compuesto
        self.peso_winrate = peso_winrate
        self.peso_beneficio = peso_beneficio
        self.peso_sharpe = peso_sharpe
        self.peso_consistencia = peso_consistencia
        
        self.simulador = SimuladorEstrategia()
    
    def calcular_fitness(self, estrategia) -> Decimal:
        """
        Calcula el fitness total de una estrategia.
        Retorna un valor entre 0 y 100 (mayor es mejor).
        """
        # Simular la estrategia sobre datos históricos
        resultados = self.simulador.simular_estrategia(
            estrategia=estrategia,
            datos_desde=self.datos_desde,
            datos_hasta=self.datos_hasta,
            activos=self.activos,
        )
        
        if resultados['operaciones_totales'] == 0:
            return Decimal("0.0000")
        
        # Calcular métricas individuales
        winrate_score = self._calcular_score_winrate(resultados['winrate'])
        beneficio_score = self._calcular_score_beneficio(resultados['beneficio_total'])
        sharpe_score = self._calcular_score_sharpe(resultados.get('sharpe_ratio', Decimal("0.00")))
        consistencia_score = self._calcular_score_consistencia(resultados)
        
        # Fitness compuesto (ponderado)
        fitness = (
            winrate_score * self.peso_winrate +
            beneficio_score * self.peso_beneficio +
            sharpe_score * self.peso_sharpe +
            consistencia_score * self.peso_consistencia
        )
        
        return fitness.quantize(Decimal("0.0001"))
    
    def _calcular_score_winrate(self, winrate: Decimal) -> Decimal:
        """
        Convierte winrate a un score de 0-100.
        Winrate ideal: 60%+ = 100 puntos
        """
        if winrate >= Decimal("60.00"):
            return Decimal("100.00")
        elif winrate >= Decimal("50.00"):
            # Escala lineal de 50-60% = 50-100 puntos
            return Decimal("50.00") + ((winrate - Decimal("50.00")) / Decimal("10.00")) * Decimal("50.00")
        elif winrate >= Decimal("40.00"):
            # Escala lineal de 40-50% = 25-50 puntos
            return Decimal("25.00") + ((winrate - Decimal("40.00")) / Decimal("10.00")) * Decimal("25.00")
        else:
            # Winrate < 40% = 0-25 puntos
            return (winrate / Decimal("40.00")) * Decimal("25.00")
    
    def _calcular_score_beneficio(self, beneficio: Decimal) -> Decimal:
        """
        Convierte beneficio total a un score de 0-100.
        Beneficio positivo = puntos positivos
        Beneficio negativo = puntos negativos (penalización)
        """
        # Normalizar: $10 = 100 puntos, $0 = 50 puntos, -$10 = 0 puntos
        if beneficio >= Decimal("10.00"):
            return Decimal("100.00")
        elif beneficio >= Decimal("0.00"):
            return Decimal("50.00") + (beneficio / Decimal("10.00")) * Decimal("50.00")
        else:
            # Penalización por pérdidas
            return max(Decimal("0.00"), Decimal("50.00") + (beneficio / Decimal("10.00")) * Decimal("50.00"))
    
    def _calcular_score_sharpe(self, sharpe: Decimal) -> Decimal:
        """
        Convierte Sharpe ratio a un score de 0-100.
        Sharpe > 2 = excelente (100 puntos)
        Sharpe > 1 = bueno (75 puntos)
        Sharpe > 0 = aceptable (50 puntos)
        Sharpe < 0 = malo (0-50 puntos)
        """
        if sharpe >= Decimal("2.00"):
            return Decimal("100.00")
        elif sharpe >= Decimal("1.00"):
            return Decimal("75.00") + ((sharpe - Decimal("1.00")) / Decimal("1.00")) * Decimal("25.00")
        elif sharpe >= Decimal("0.00"):
            return Decimal("50.00") + (sharpe / Decimal("1.00")) * Decimal("25.00")
        else:
            # Sharpe negativo = penalización
            return max(Decimal("0.00"), Decimal("50.00") + (sharpe / Decimal("1.00")) * Decimal("50.00"))
    
    def _calcular_score_consistencia(self, resultados: Dict) -> Decimal:
        """
        Mide la consistencia de la estrategia.
        Estrategias consistentes (pocas pérdidas consecutivas) = mejor score.
        """
        max_drawdown = resultados.get('max_drawdown', Decimal("0.00"))
        operaciones_totales = resultados.get('operaciones_totales', 0)
        
        if operaciones_totales == 0:
            return Decimal("0.00")
        
        # Drawdown bajo = consistente = mejor score
        if max_drawdown <= Decimal("2.00"):
            return Decimal("100.00")
        elif max_drawdown <= Decimal("5.00"):
            return Decimal("75.00") + ((Decimal("5.00") - max_drawdown) / Decimal("3.00")) * Decimal("25.00")
        elif max_drawdown <= Decimal("10.00"):
            return Decimal("50.00") + ((Decimal("10.00") - max_drawdown) / Decimal("5.00")) * Decimal("25.00")
        else:
            return max(Decimal("0.00"), Decimal("50.00") - ((max_drawdown - Decimal("10.00")) / Decimal("10.00")) * Decimal("50.00"))

