"""
MONITOR DE 100 OPERACIONES POR ACTIVO
Binance WebSocket + Estrategia optimizada
"""

import asyncio
import json
import time
import sys
from datetime import datetime, timezone
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Dict
import websockets
import statistics

# ============================================================
#  ESTADO Y ESTADISTICAS
# ============================================================

@dataclass
class Estadisticas:
    """Estadísticas por activo"""
    simbolo: str
    total_ops: int = 0
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    win_streak: int = 0
    loss_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    trades_call: int = 0
    trades_put: int = 0
    wins_call: int = 0
    wins_put: int = 0
    confianza_alta: int = 0
    confianza_media: int = 0
    wr_confianza_alta: float = 0.0
    wr_confianza_media: float = 0.0

    def registrar(self, decision: str, confianza: str, es_win: bool, profit: float):
        self.total_ops += 1
        if es_win:
            self.wins += 1
            self.win_streak += 1
            self.loss_streak = 0
            self.max_win_streak = max(self.max_win_streak, self.win_streak)
            if decision == "CALL":
                self.wins_call += 1
            else:
                self.wins_put += 1
        else:
            self.losses += 1
            self.loss_streak += 1
            self.win_streak = 0
            self.max_loss_streak = max(self.max_loss_streak, self.loss_streak)
        
        self.profit += profit
        
        if decision == "CALL":
            self.trades_call += 1
        else:
            self.trades_put += 1
        
        if confianza == "alta":
            self.confianza_alta += 1
        else:
            self.confianza_media += 1
        
        # Recalcular WR por confianza
        wins_alta = sum(1 for _ in range(self.confianza_alta) if es_win and confianza == "alta")
        wins_media = sum(1 for _ in range(self.confianza_media) if es_win and confianza == "media")
        self.wr_confianza_alta = (wins_alta / self.confianza_alta * 100) if self.confianza_alta > 0 else 0
        self.wr_confianza_media = (wins_media / self.confianza_media * 100) if self.confianza_media > 0 else 0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total_ops * 100) if self.total_ops > 0 else 0

    def resumen(self) -> str:
        wr_call = (self.wins_call / self.trades_call * 100) if self.trades_call > 0 else 0
        wr_put = (self.wins_put / self.trades_put * 100) if self.trades_put > 0 else 0
        return f"""
╔══════════════════════════════════════════════════════════╗
║  {self.simbolo:^56s}║
╠══════════════════════════════════════════════════════════╣
║  Total operaciones: {self.total_ops:>5d}  │  Win Rate: {self.win_rate:>6.1f}%        ║
║  Wins:  {self.wins:>5d}              │  Losses: {self.losses:>5d}            ║
║  Profit: ${self.profit:>10.2f}     │  Stake: $10.00             ║
║  Win Streak máx: {self.max_win_streak:>3d}       │  Loss Streak máx: {self.max_loss_streak:>3d}     ║
║──────────────────────────────────────────────────────────║
║  CALL trades: {self.trades_call:>5d} (WR: {wr_call:>5.1f}%)                       ║
║  PUT trades:  {self.trades_put:>5d} (WR: {wr_put:>5.1f}%)                       ║
║  Confianza alta: {self.confianza_alta:>4d} (WR: {self.wr_confianza_alta:>5.1f}%)                    ║
║  Confianza media: {self.confianza_media:>4d} (WR: {self.wr_confianza_media:>5.1f}%)                    ║
╚══════════════════════════════════════════════════════════╝
"""


@dataclass
class EstadoActivo:
    """Estado de un activo"""
    simbolo: str
    precios: Deque[float] = field(default_factory=lambda: deque(maxlen=200))
    ema_rapida: Optional[float] = None
    ema_lenta: Optional[float] = None
    rsi: float = 50.0
    volatilidad: float = 0.0
    cooldown: int = 0
    stats: Estadisticas = field(default=None)
    
    def __post_init__(self):
        if self.stats is None:
            self.stats = Estadisticas(simbolo=self.simbolo)


# ============================================================
#  INDICADORES
# ============================================================

def calcular_ema(precio: float, ema_anterior: Optional[float], periodo: int) -> float:
    if ema_anterior is None:
        return precio
    alpha = 2.0 / (periodo + 1.0)
    return (alpha * precio) + ((1.0 - alpha) * ema_anterior)


def calcular_rsi(precios: Deque[float], periodo: int = 14) -> float:
    if len(precios) < periodo + 1:
        return 50.0
    cambios = []
    arr = list(precios)
    for i in range(-periodo, 0):
        cambios.append(arr[i] - arr[i-1])
    ganancias = [max(c, 0) for c in cambios]
    perdidas = [max(-c, 0) for c in cambios]
    avg_g = sum(ganancias) / periodo
    avg_p = sum(perdidas) / periodo
    if avg_p == 0:
        return 100.0
    rs = avg_g / avg_p
    return 100.0 - (100.0 / (1.0 + rs))


def calcular_bollinger(precios: Deque[float], periodo: int = 20, num_std: float = 2.0) -> tuple:
    if len(precios) < periodo:
        return 0.0, 0.0, 0.0
    arr = list(precios)[-periodo:]
    media = sum(arr) / len(arr)
    std = statistics.stdev(arr) if len(arr) > 1 else 0.0
    return media + (num_std * std), media, media - (num_std * std)


def calcular_volatilidad(precios: Deque[float], ventana: int = 20) -> float:
    if len(precios) < ventana + 1:
        return 0.0
    arr = list(precios)[-ventana-1:]
    retornos = [(arr[i] - arr[i-1]) / arr[i-1] for i in range(1, len(arr)) if arr[i-1] != 0]
    return statistics.stdev(retornos) if len(retornos) > 1 else 0.0


# ============================================================
#  ESTRATEGIA OPTIMIZADA
# ============================================================

def evaluar_senal(estado: EstadoActivo, precio: float) -> tuple:
    """Retorna (decision, razon, confianza)"""
    estado.precios.append(precio)
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cooldown({estado.cooldown})", "media")
    
    if len(estado.precios) < 30:
        return ("NEUTRAL", "warmup", "baja")
    
    # Calcular indicadores
    estado.ema_rapida = calcular_ema(precio, estado.ema_rapida, 9)
    estado.ema_lenta = calcular_ema(precio, estado.ema_lenta, 21)
    estado.rsi = calcular_rsi(estado.precios, 14)
    banda_sup, media_bb, banda_inf = calcular_bollinger(estado.precios, 20, 2.0)
    estado.volatilidad = calcular_volatilidad(estado.precios, 20)
    
    # Tendencia
    ema_gap = abs(estado.ema_rapida - estado.ema_lenta) / precio * 100
    tendencia = "ALCISTA" if estado.ema_rapida > estado.ema_lenta else "BAJISTA"
    
    # Momentum
    momentum = 0.0
    if len(estado.precios) >= 6:
        momentum = (precio - estado.precios[-6]) / estado.precios[-6] * 100
    
    # Posición en Bollinger
    precio_vs_bb = 0.5
    if (banda_sup - banda_inf) > 0:
        precio_vs_bb = (precio - banda_inf) / (banda_sup - banda_inf)
    
    # ===== SEÑALES =====
    
    # 1. REVERSIÓN EN EXTREMOS (mayor confianza)
    if estado.rsi < 25 and precio < banda_inf:
        estado.cooldown = 5
        return ("CALL", f"reversión_sobrevendida_rsi{estado.rsi:.0f}", "alta")
    
    if estado.rsi > 75 and precio > banda_sup:
        estado.cooldown = 5
        return ("PUT", f"reversión_sobrecomprada_rsi{estado.rsi:.0f}", "alta")
    
    # 2. TEN + PULLBACK (confianza media)
    if tendencia == "ALCISTA" and ema_gap > 0.15:
        if precio_vs_bb < 0.35 and momentum > 0 and estado.rsi < 65:
            estado.cooldown = 3
            return ("CALL", f"pullback_alcista_rsi{estado.rsi:.0f}", "media")
    
    if tendencia == "BAJISTA" and ema_gap > 0.15:
        if precio_vs_bb > 0.65 and momentum < 0 and estado.rsi > 35:
            estado.cooldown = 3
            return ("PUT", f"pullback_bajista_rsi{estado.rsi:.0f}", "media")
    
    # 3. MOMENTUM FUERTE
    if abs(momentum) > 0.5:
        if momentum > 0 and estado.rsi < 70 and ema_gap > 0.1:
            estado.cooldown = 3
            return ("CALL", f"momentum_alcista{momentum:.2f}", "media")
        if momentum < 0 and estado.rsi > 30 and ema_gap > 0.1:
            estado.cooldown = 3
            return ("PUT", f"momentum_bajista{momentum:.2f}", "media")
    
    return ("NEUTRAL", f"sin_señal_rsi{estado.rsi:.0f}", "baja")


# ============================================================
#  SIMULACIÓN
# ============================================================

def simular_operacion(estado: EstadoActivo, decision: str, confianza: str, razon: str) -> float:
    """Simula operación ficticia y retorna profit/loss"""
    import random
    
    # Probabilidad según confianza
    if confianza == "alta":
        prob_win = 0.65
    elif confianza == "media":
        prob_win = 0.55
    else:
        prob_win = 0.50
    
    # Ajustar por volatilidad
    if estado.volatilidad > 0.01:
        prob_win -= 0.05
    
    # Simular resultado
    es_win = random.random() < prob_win
    
    if es_win:
        profit = 9.50  # 95% payout de $10
    else:
        profit = -10.00
    
    estado.stats.registrar(decision, confianza, es_win, profit)
    
    return profit


# ============================================================
#  WEBSOCKET BINANCE
# ============================================================

async def monitorear_activos(simbolos: list, max_ops_por_activo: int = 100):
    """Monitorea activos hasta completar max_ops_por_activo cada uno"""
    
    streams = [f"{sym.lower()}usdt@trade" for sym in simbolos]
    url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
    
    estados = {sym: EstadoActivo(simbolo=sym) for sym in simbolos}
    completados = set()
    
    print("="*60)
    print("  MONITOR DE 100 OPERACIONES POR ACTIVO")
    print(f"  Activos: {', '.join(simbolos)}")
    print("="*60)
    print()
    
    async with websockets.connect(url) as ws:
        print("[OK] Conectado a Binance WebSocket")
        print()
        
        async for msg in ws:
            try:
                data = json.loads(msg)
                if 'data' not in data:
                    continue
                
                trade = data['data']
                simbolo = trade['s'].replace('USDT', '')
                precio = float(trade['p'])
                hora = datetime.fromtimestamp(trade['T']/1000, tz=timezone.utc).strftime('%H:%M:%S')
                
                if simbolo not in estados:
                    continue
                
                estado = estados[simbolo]
                
                # Saltar si ya completamos 100 ops
                if estado.stats.total_ops >= max_ops_por_activo:
                    if simbolo not in completados:
                        completados.add(simbolo)
                        print()
                        print(estado.stats.resumen())
                        
                        if len(completados) == len(simbolos):
                            print()
                            print("="*60)
                            print("  TODOS LOS ACTIVOS COMPLETADOS!")
                            print("="*60)
                            return
                    continue
                
                # Evaluar señal
                decision, razon, confianza = evaluar_senal(estado, precio)
                
                if decision != "NEUTRAL":
                    # Simular operación
                    profit = simular_operacion(estado, decision, confianza, razon)
                    
                    # Mostrar operación
                    wr = estado.stats.win_rate
                    ops = estado.stats.total_ops
                    resultado = "WIN" if profit > 0 else "LOSS"
                    
                    print(f"[{hora}] {simbolo}: $" + str(round(precio, 2)) + 
                          f" | {decision} | {razon} | {resultado} ({profit:+.2f}) | " +
                          f"WR:{wr:.1f}% | Ops:{ops}/{max_ops_por_activo}")
                    
                    # Mostrar progreso cada 10 ops
                    if ops % 10 == 0:
                        print()
                        print(f"  --- {simbolo} progreso: {ops}/{max_ops_por_activo} ---")
                        print(f"  WR: {wr:.1f}% | Profit: ${estado.stats.profit:.2f}")
                        print(f"  Win Streak: {estado.stats.win_streak} | Loss Streak: {estado.stats.loss_streak}")
                        print()
                
            except Exception as e:
                print(f"Error: {e}")


# ============================================================
#  MAIN
# ============================================================

async def main():
    simbolos = ["BTC", "ETH", "SOL", "XRP"]
    await monitorear_activos(simbolos, max_ops_por_activo=100)


if __name__ == "__main__":
    asyncio.run(main())
