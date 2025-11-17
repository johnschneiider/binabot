"""
Servicios para entrenamiento de IA en tiempo real.
"""
from decimal import Decimal
from typing import Optional, Dict
from django.utils import timezone
from django.db import transaction
from historial.models import Operacion
from ai_trading.models import EstrategiaGenetica, TradeIA, EntrenamientoIA
from ai_trading.genetico import SimuladorEstrategia


class EntrenadorIATiempoReal:
    """
    Entrena estrategias de IA observando trades reales del bot principal.
    Castiga cuando pierde, recompensa cuando gana.
    """
    
    def __init__(self, estrategia: EstrategiaGenetica):
        self.estrategia = estrategia
        self.simulador = SimuladorEstrategia()
        self.reward_ganancia = Decimal("1.0")  # Recompensa por ganar
        self.reward_perdida = Decimal("-1.5")  # Castigo por perder (más fuerte)
        self.reward_empate = Decimal("0.0")  # Neutral para empates
    
    def observar_trade_real(self, operacion: Operacion) -> Optional[TradeIA]:
        """
        Observa un trade real del bot principal y evalúa si la estrategia
        habría tomado la misma decisión.
        """
        # Verificar si la estrategia habría generado una señal para este activo
        # en el momento del trade
        if not self._estrategia_habria_operado(operacion):
            return None
        
        # Crear trade de IA basado en el trade real
        trade_ia = TradeIA.objects.create(
            estrategia=self.estrategia,
            activo=operacion.activo,
            direccion=operacion.direccion,
            precio_entrada=operacion.precio_entrada,
            precio_salida=operacion.precio_cierre if operacion.precio_cierre else None,
            monto_invertido=operacion.monto_invertido,
            resultado=TradeIA.Resultado.PENDIENTE if operacion.resultado == Operacion.Resultado.PENDIENTE
            else TradeIA.Resultado.GANADO if operacion.resultado == Operacion.Resultado.GANADA
            else TradeIA.Resultado.PERDIDO,
            beneficio=operacion.beneficio,
            hora_inicio=operacion.hora_inicio,
            hora_fin=operacion.hora_fin,
        )
        
        # Calcular reward y actualizar estrategia
        if operacion.resultado != Operacion.Resultado.PENDIENTE:
            self._procesar_resultado_trade(trade_ia, operacion)
        
        return trade_ia
    
    def _estrategia_habria_operado(self, operacion: Operacion) -> bool:
        """
        Verifica si la estrategia habría generado una señal para operar
        en este activo en el momento del trade.
        """
        # Obtener ticks anteriores al trade
        from historial.models import Tick
        
        ticks_anteriores = Tick.objects.filter(
            activo=operacion.activo,
            epoch__lt=operacion.hora_inicio,
        ).order_by('-epoch')[:self.estrategia.ventana_ticks]
        
        if ticks_anteriores.count() < self.estrategia.ventana_ticks:
            return False
        
        # Simular la estrategia con esos ticks
        ticks_list = list(reversed(ticks_anteriores))
        senal = self.simulador._generar_senal(ticks_list, self.estrategia)
        
        if not senal:
            return False
        
        # Verificar si la dirección coincide
        direccion_estrategia = senal['direccion']
        return direccion_estrategia == operacion.direccion
    
    def _procesar_resultado_trade(self, trade_ia: TradeIA, operacion: Operacion) -> None:
        """
        Procesa el resultado de un trade y actualiza el fitness de la estrategia.
        """
        # Calcular reward
        if operacion.resultado == Operacion.Resultado.GANADA:
            reward = self.reward_ganancia
        elif operacion.resultado == Operacion.Resultado.PERDIDA:
            reward = self.reward_perdida
        else:  # Empate
            reward = self.reward_empate
        
        trade_ia.reward = reward
        trade_ia.save(update_fields=["reward"])
        
        # Actualizar métricas de la estrategia
        with transaction.atomic():
            self.estrategia.refresh_from_db()
            self.estrategia.operaciones_evaluadas += 1
            
            if operacion.resultado == Operacion.Resultado.GANADA:
                self.estrategia.ganadas += 1
            elif operacion.resultado == Operacion.Resultado.PERDIDA:
                self.estrategia.perdidas += 1
            
            self.estrategia.beneficio_total = (
                self.estrategia.beneficio_total + operacion.beneficio
            ).quantize(Decimal("0.01"))
            
            # Actualizar fitness con reward
            # El fitness se actualiza incrementalmente con el reward
            self.estrategia.fitness = (
                self.estrategia.fitness + reward
            ).quantize(Decimal("0.0001"))
            
            # Asegurar que el fitness no sea negativo
            if self.estrategia.fitness < Decimal("0.00"):
                self.estrategia.fitness = Decimal("0.00")
            
            self.estrategia.actualizar_metricas()
            self.estrategia.ultima_evaluacion = timezone.now()
            self.estrategia.save(
                update_fields=[
                    "operaciones_evaluadas",
                    "ganadas",
                    "perdidas",
                    "beneficio_total",
                    "fitness",
                    "winrate",
                    "ultima_evaluacion",
                    "actualizada",
                ]
            )


class ObservadorTradesReales:
    """
    Observa trades reales del bot principal y los procesa para entrenar la IA.
    """
    
    def __init__(self, entrenamiento: EntrenamientoIA):
        self.entrenamiento = entrenamiento
        self.estrategias_activas = list(
            EstrategiaGenetica.objects.filter(activa=True)
        )
        self.ultimo_trade_procesado_id = None
    
    def procesar_nuevos_trades(self) -> int:
        """
        Procesa nuevos trades reales desde la última vez.
        Retorna la cantidad de trades procesados.
        """
        # Obtener trades reales nuevos
        operaciones = Operacion.objetos.reales().exclude(
            resultado=Operacion.Resultado.PENDIENTE
        ).order_by('id')
        
        if self.ultimo_trade_procesado_id:
            operaciones = operaciones.filter(id__gt=self.ultimo_trade_procesado_id)
        
        trades_procesados = 0
        
        for operacion in operaciones:
            # Procesar con cada estrategia activa
            for estrategia in self.estrategias_activas:
                entrenador = EntrenadorIATiempoReal(estrategia)
                trade_ia = entrenador.observar_trade_real(operacion)
                if trade_ia:
                    trades_procesados += 1
            
            # Actualizar último trade procesado
            if not self.ultimo_trade_procesado_id or operacion.id > self.ultimo_trade_procesado_id:
                self.ultimo_trade_procesado_id = operacion.id
        
        return trades_procesados

