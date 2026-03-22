from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math

from .estrategia_eurusd import (
    IndicadorEMA35,
    ConstructorVelasM5,
    evaluar_senal_eurusd,
    evaluar_senal_simple,
    evaluar_senal_momentum,
    evaluar_senal_reversion,
    evaluar_senal_tendencia_simple,
    SenalEURUSD,
)
from .models import OperacionBacktest


@dataclass(frozen=True)
class ResultadoBacktest:
    total_ops: int
    wins: int
    losses: int
    winrate: float
    pnl_total: float
    profit_factor: float
    max_drawdown: float
    expectativa: float


@dataclass(frozen=True)
class ParametrosBacktest:
    ema_periodo: int = 35
    pullback_min: int = 1
    pullback_max: int = 3
    expiration_candles: int = 1
    payout_win: float = 0.95  # 95% payout typical para binary
    stake: float = 1.0


class BacktestEURUSD:
    """
    BACKTEST PARA ESTRATEGIA EURUSD SEGÚN ESTRATEGIA.TXT
    
    Parámetros:
    - EMA periodo: 20-50 (optimizable)
    - Pullback: 1-4 velas (optimizable)
    - Expiration: 1-3 velas (optimizable)
    - Payout: % de ganancia por operación ganadora
    """
    
    def __init__(
        self,
        params: Optional[ParametrosBacktest] = None,
    ):
        self.params = params or ParametrosBacktest()
        self._ema35 = IndicadorEMA35(periodo=self.params.ema_periodo)
        self._constructor_velas = ConstructorVelasM5()
        self._velas: list[dict] = []
        self._operaciones: list[dict] = []
        self._capital: float = 100.0
        self._capital_max: float = 100.0
        self._drawdown_max: float = 0.0
        self._capital_history: list[float] = [100.0]
        self._ultimo_precio: float = 0.0
        self._precio_anterior: float = 0.0
        self._ultimo_epoch: int = 0
    
    def ejecutar(
        self,
        ticks: list[tuple[float, int]],
        debug: bool = False,
    ) -> ResultadoBacktest:
        """
        Ejecuta backtest sobre una lista de ticks (precio, epoch).
        
        Retorna métricas de performance.
        """
        # Procesar ticks y construir velas
        for precio, epoch in ticks:
            # ACTUALIZAR EMA EN CADA TICK (no solo en velas)
            self._precio_anterior = self._ultimo_precio
            self._ema35.actualizar(precio, epoch)
            self._ultimo_precio = precio
            self._ultimo_epoch = epoch
            
            vela_completada = self._constructor_velas.agregar_tick(precio, epoch)
            
            if vela_completada:
                self._velas.append(vela_completada)
                self._procesar_vela(vela_completada, debug=debug)
        
        if debug:
            print(f"DEBUG: Total velas generadas: {len(self._velas)}")
        
        return self._obtener_resultados()
    
    def _procesar_vela(self, vela: dict, debug: bool = False):
        """Procesa una vela completada y evalúa señales."""
        # El EMA ya se actualiza en cada tick, no aquí
        
        ema_valor = self._ema35.valor
        ema_str = f"{ema_valor:.5f}" if ema_valor else "None"
        
        if debug and len(self._velas) % 5 == 0:
            print(f"DEBUG Vela{len(self._velas)}: precio={vela['close']:.5f} ema={ema_str} listo={self._ema35.listo} precios_en_ema={len(self._ema35._precios)}")
        
        if not self._ema35.listo:
            return
        
        if debug:
            tendencia = self._ema35.obtener_tendencia()
            pendiente = self._ema35._calcular_pendiente()
            ema_valor = self._ema35.valor
            ema_str = f"{ema_valor:.5f}" if ema_valor else "None"
            diff = self._ultimo_precio - ema_valor if ema_valor else 0
            print(f"DEBUG: Vela {len(self._velas)} | precio={vela['close']:.5f} ema={ema_str} diff={diff:.6f} tendencia={tendencia.direccion if tendencia else 'N/A'}")
        
        # Evaluar señal (versión momentum)
        if len(self._velas) >= 3:
            vela_actual = vela
            vela_1 = self._velas[-2]
            vela_2 = self._velas[-3]
            
            # Recolectar precios de últimas 10 velas
            ultimos_precios = [v["close"] for v in self._velas[-10:]]
            ultimos_precios.append(vela_actual["close"])
            
            # Usar estrategia de tendencia simple
            senal = evaluar_senal_tendencia_simple(
                precios_recientes=ultimos_precios,
            )
            
            if senal.decision != "NO_OPERAR":
                print(f"SEÑAL: {senal.decision} - {senal.razon}")
        else:
            senal = SenalEURUSD(decision="NO_OPERAR", razon="Sin suficientes velas")
        
        if senal.decision == "NO_OPERAR":
            return
        
        # Ejecutar operación virtual
        self._ejecutar_operacion(vela, senal)
    
    def _ejecutar_operacion(self, vela_senal: dict, senal: SenalEURUSD):
        """Ejecuta una operación virtual."""
        precio_entrada = vela_senal["close"]
        
        # Usar la última vela disponible para el resultado
        if len(self._velas) < 2:
            return
        
        # Usar la siguiente vela para determinar resultado
        vela_salida = self._velas[-1]
        precio_salida = vela_salida["close"]
        
        # Determinar resultado
        if senal.decision == "CALL":
            # Ganamos si precio_subida > entrada
            resultado = "WIN" if precio_salida > precio_entrada else "LOSS"
        else:  # PUT
            resultado = "WIN" if precio_salida < precio_entrada else "LOSS"
        
        # Calcular PnL (considerando payout)
        if resultado == "WIN":
            pnl = self.params.stake * self.params.payout_win
        else:
            pnl = -self.params.stake
        
        # Actualizar capital
        self._capital += pnl
        self._capital_history.append(self._capital)
        self._capital_max = max(self._capital_max, self._capital)
        
        # Calcular drawdown
        drawdown = (self._capital_max - self._capital) / self._capital_max
        self._drawdown_max = max(self._drawdown_max, drawdown)
        
        # Guardar operación
        self._operaciones.append({
            "direccion": senal.decision,
            "precio_entrada": precio_entrada,
            "precio_salida": precio_salida,
            "resultado": resultado,
            "pnl": pnl,
            "epoch_entrada": vela_senal["epoch_inicio"],
            "epoch_salida": vela_salida["epoch_inicio"],
            "senal_detalle": {
                "razon": senal.razon,
                "tendencia": senal.tendencia.direccion if senal.tendencia else None,
                "pullback_count": senal.pullback_count,
            }
        })
    
    def _obtener_resultados(self) -> ResultadoBacktest:
        """Calcula métricas finales del backtest."""
        total_ops = len(self._operaciones)
        
        if total_ops == 0:
            return ResultadoBacktest(
                total_ops=0,
                wins=0,
                losses=0,
                winrate=0.0,
                pnl_total=0.0,
                profit_factor=0.0,
                max_drawdown=0.0,
                expectativa=0.0,
            )
        
        wins = sum(1 for op in self._operaciones if op["resultado"] == "WIN")
        losses = total_ops - wins
        
        pnl_total = sum(op["pnl"] for op in self._operaciones)
        
        winrate = (wins / total_ops) * 100 if total_ops > 0 else 0.0
        
        # Profit factor
        ganancia_total = sum(op["pnl"] for op in self._operaciones if op["pnl"] > 0)
        perdida_total = abs(sum(op["pnl"] for op in self._operaciones if op["pnl"] < 0))
        profit_factor = ganancia_total / perdida_total if perdida_total > 0 else 0.0
        
        # Expectativa matemática
        winrate_decimal = wins / total_ops
        expectativa = (winrate_decimal * self.params.payout_win) - ((1 - winrate_decimal) * 1.0)
        
        return ResultadoBacktest(
            total_ops=total_ops,
            wins=wins,
            losses=losses,
            winrate=winrate,
            pnl_total=pnl_total,
            profit_factor=profit_factor,
            max_drawdown=self._drawdown_max * 100,  # En porcentaje
            expectativa=expectativa,
        )
    
    def guardar_en_db(self):
        """Guarda las operaciones del backtest en la base de datos."""
        from django.utils import timezone
        import datetime
        
        for op in self._operaciones:
            OperacionBacktest.objects.create(
                vela_entrada_id=0,  # TODO: link to actual vela
                direccion=op["direccion"],
                precio_entrada=op["precio_entrada"],
                precio_salida=op["precio_salida"],
                resultado=op["resultado"],
                pnl=op["pnl"],
                senal_detalle=op["senal_detalle"],
                epoch_entrada=op["epoch_entrada"],
                epoch_salida=op["epoch_salida"],
            )


def optimizar_parametros(
    ticks: list[tuple[float, int]],
    ema_rango: range = range(20, 51),
    pullback_rango: range = range(1, 5),
) -> tuple[ParametrosBacktest, ResultadoBacktest]:
    """
    OPTIMIZA PARÁMETROS SEGÚN ESTRATEGIA.TXT
    
    Restricciones de optimización:
    - Profit factor > 1.3
    - Drawdown controlado
    - Consistencia en validación
    """
    mejor_params = None
    mejor_resultado = None
    mejor_score = -float("inf")
    
    for ema_periodo in ema_rango:
        for pullback_min in pullback_rango:
            for pullback_max in range(pullback_min, 5):
                params = ParametrosBacktest(
                    ema_periodo=ema_periodo,
                    pullback_min=pullback_min,
                    pullback_max=pullback_max,
                )
                
                backtest = BacktestEURUSD(params)
                resultado = backtest.ejecutar(ticks)
                
                # Validar según restricciones
                if resultado.profit_factor < 1.3:
                    continue
                
                if resultado.max_drawdown > 20:  # Max 20% drawdown
                    continue
                
                if resultado.total_ops < 30:  # Mínimo de operaciones
                    continue
                
                # Score: ponderar profit factor y bajo drawdown
                score = resultado.profit_factor * (100 - resultado.max_drawdown) / 100
                
                if score > mejor_score:
                    mejor_score = score
                    mejor_params = params
                    mejor_resultado = resultado
    
    if mejor_params is None:
        # Devolver defaults si no hay buena configuración
        return ParametrosBacktest(), ResultadoBacktest(
            total_ops=0, wins=0, losses=0, winrate=0.0,
            pnl_total=0.0, profit_factor=0.0, max_drawdown=0.0, expectativa=0.0
        )
    
    return mejor_params, mejor_resultado
