"""
Simulador de estrategias genéticas sobre datos históricos.
"""
from decimal import Decimal
from typing import Dict, List, Optional
from django.utils import timezone
from historial.models import Tick, Operacion
from core.models import ActivoPermitido
from ai_trading.models import EstrategiaGenetica


class SimuladorEstrategia:
    """
    Simula una estrategia genética sobre datos históricos de ticks.
    """
    
    def simular_estrategia(
        self,
        estrategia: EstrategiaGenetica,
        datos_desde,
        datos_hasta,
        activos: List[str],
        monto_por_trade: Decimal = Decimal("1.00"),
    ) -> Dict:
        """
        Simula la estrategia sobre datos históricos y retorna resultados.
        """
        operaciones_ganadas = 0
        operaciones_perdidas = 0
        beneficios = []
        drawdowns = []
        balance_actual = Decimal("100.00")  # Balance inicial simulado
        balance_maximo = balance_actual
        drawdown_actual = Decimal("0.00")
        max_drawdown = Decimal("0.00")
        
        # Obtener ticks para cada activo en el rango de fechas
        total_activos = len(activos)
        for idx, activo in enumerate(activos, 1):
            ticks = Tick.objects.filter(
                activo=activo,
                epoch__gte=datos_desde,
                epoch__lte=datos_hasta,
            ).order_by('epoch')
            
            if ticks.count() < estrategia.ventana_ticks:
                continue
            
            # Procesar ticks en ventanas
            ticks_list = list(ticks)
            for i in range(len(ticks_list) - estrategia.ventana_ticks):
                ventana = ticks_list[i:i + estrategia.ventana_ticks]
                
                # Generar señal según la estrategia
                senal = self._generar_senal(ventana, estrategia)
                
                if not senal:
                    continue
                
                # Simular operación
                tick_siguiente = ticks_list[i + estrategia.ventana_ticks] if i + estrategia.ventana_ticks < len(ticks_list) else None
                if not tick_siguiente:
                    continue
                
                resultado = self._evaluar_operacion(
                    ventana[-1],  # Precio de entrada
                    tick_siguiente,  # Precio de salida
                    senal['direccion'],
                    monto_por_trade,
                )
                
                if resultado['ganada']:
                    operaciones_ganadas += 1
                    balance_actual += resultado['beneficio']
                else:
                    operaciones_perdidas += 1
                    balance_actual -= abs(resultado['beneficio'])
                
                beneficios.append(resultado['beneficio'])
                
                # Calcular drawdown
                if balance_actual > balance_maximo:
                    balance_maximo = balance_actual
                    drawdown_actual = Decimal("0.00")
                else:
                    drawdown_actual = balance_maximo - balance_actual
                    if drawdown_actual > max_drawdown:
                        max_drawdown = drawdown_actual
        
        operaciones_totales = operaciones_ganadas + operaciones_perdidas
        winrate = (
            (Decimal(operaciones_ganadas) / Decimal(operaciones_totales) * Decimal("100"))
            if operaciones_totales > 0
            else Decimal("0.00")
        ).quantize(Decimal("0.01"))
        
        beneficio_total = sum(beneficios) if beneficios else Decimal("0.00")
        sharpe_ratio = self._calcular_sharpe_ratio(beneficios) if len(beneficios) > 1 else Decimal("0.00")
        
        return {
            'operaciones_totales': operaciones_totales,
            'operaciones_ganadas': operaciones_ganadas,
            'operaciones_perdidas': operaciones_perdidas,
            'winrate': winrate,
            'beneficio_total': beneficio_total.quantize(Decimal("0.01")),
            'sharpe_ratio': sharpe_ratio.quantize(Decimal("0.0001")),
            'max_drawdown': max_drawdown.quantize(Decimal("0.01")),
            'balance_final': balance_actual.quantize(Decimal("0.01")),
        }
    
    def _generar_senal(self, ventana_ticks: List[Tick], estrategia: EstrategiaGenetica) -> Optional[Dict]:
        """
        Genera una señal de trading basada en la estrategia genética.
        """
        if len(ventana_ticks) < 2:
            return None
        
        precio_inicial = ventana_ticks[0].precio
        precio_final = ventana_ticks[-1].precio
        
        if precio_inicial == Decimal("0.00"):
            return None
        
        variacion = abs((precio_final - precio_inicial) / precio_inicial * Decimal("100"))
        
        # Verificar umbrales de la estrategia
        if variacion < estrategia.umbral_variacion_min:
            return None
        
        direccion = "CALL" if precio_final > precio_inicial else "PUT"
        confianza = min(variacion, Decimal("99.99"))
        
        if confianza < estrategia.umbral_confianza_min:
            return None
        
        return {
            'direccion': direccion,
            'confianza': confianza,
            'variacion': variacion,
        }
    
    def _evaluar_operacion(
        self,
        tick_entrada: Tick,
        tick_salida: Tick,
        direccion: str,
        monto: Decimal,
    ) -> Dict:
        """
        Evalúa si una operación fue ganada o perdida.
        """
        precio_entrada = tick_entrada.precio
        precio_salida = tick_salida.precio
        
        ganada = False
        if direccion == "CALL":
            ganada = precio_salida > precio_entrada
        else:  # PUT
            ganada = precio_salida < precio_entrada
        
        # Beneficio simplificado: si gana, gana el monto; si pierde, pierde el monto
        beneficio = monto if ganada else -monto
        
        return {
            'ganada': ganada,
            'beneficio': beneficio,
        }
    
    def _calcular_sharpe_ratio(self, beneficios: List[Decimal]) -> Decimal:
        """
        Calcula el ratio de Sharpe (medida de riesgo/retorno).
        """
        if len(beneficios) < 2:
            return Decimal("0.00")
        
        # Calcular promedio y desviación estándar
        import statistics
        beneficios_float = [float(b) for b in beneficios]
        promedio = Decimal(str(statistics.mean(beneficios_float)))
        desviacion = Decimal(str(statistics.stdev(beneficios_float))) if len(beneficios) > 1 else Decimal("1.00")
        
        if desviacion == Decimal("0.00"):
            return Decimal("0.00")
        
        # Sharpe ratio = promedio / desviación estándar
        sharpe = promedio / desviacion
        return sharpe.quantize(Decimal("0.0001"))

