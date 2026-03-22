"""
Bot simplificado para probar la estrategia Momentum Breakout
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from estrategia_momentum import EstadoMomentum, evaluar_momentum_breakout, reportar_resulto
from estrategia_config import MOMENTUM_PARAMS, RISK_PARAMS, SYMBOL_CONFIG
from gestion_riesgo.models import Cuenta, OperacionDeriv, TickDerivHistorico
from django.utils import timezone as django_timezone
import asyncio
import time

# Simulación simple
def simular_trades():
    print("=== SIMULACIÓN DE TRADAS CON MOMENTUM BREAKOUT ===")
    
    # Parámetros
    capital_inicial = 100.0
    capital = capital_inicial
    target_diario = capital_inicial * 0.10  # 10%
    stop_diario = capital_inicial * 0.05    # 5%
    
    print(f"Capital inicial: ${capital_inicial:.2f}")
    print(f"Target diario: ${target_diario:.2f} (10%)")
    print(f"Stop diario: ${stop_diario:.2f} (5%)")
    
    # Obtener datos históricos
    cuenta = Cuenta.objects.filter(simbolo='R_10').first()
    if not cuenta:
        print("No se encontró cuenta R_10")
        return
    
    ticks = list(TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch'))
    print(f"Ticks disponibles: {len(ticks)}")
    
    if len(ticks) < 1000:
        print("No hay suficientes datos")
        return
    
    # Simular
    estado = EstadoMomentum()
    trades = []
    wins = 0
    losses = 0
    profit_total = 0.0
    
    print("\nIniciando simulación...")
    
    for i in range(100, len(ticks)):
        tick = ticks[i]
        precio = tick.precio
        
        # Evaluar señal
        resultado = evaluar_momentum_breakout(precio, estado, **MOMENTUM_PARAMS)
        
        if resultado['decision'] in ['COMPRA', 'VENTA']:
            # Simular trade de 5 ticks
            stake = resultado['stake']
            
            if i + 5 < len(ticks):
                precio_entrada = precio
                precio_salida = ticks[i + 5].precio
                
                # Determinar resultado
                if resultado['decision'] == 'COMPRA':
                    # CALL: gana si precio sube
                    if precio_salida > precio_entrada:
                        profit = stake * 0.85  # Payout 85%
                        resultado_trade = 'WIN'
                        wins += 1
                    else:
                        profit = -stake
                        resultado_trade = 'LOSS'
                        losses += 1
                else:  # VENTA
                    # PUT: gana si precio baja
                    if precio_salida < precio_entrada:
                        profit = stake * 0.85
                        resultado_trade = 'WIN'
                        wins += 1
                    else:
                        profit = -stake
                        resultado_trade = 'LOSS'
                        losses += 1
                
                # Actualizar capital
                capital += profit
                profit_total += profit
                
                # Registrar trade
                trade = {
                    'tick': i,
                    'direccion': resultado['decision'],
                    'stake': stake,
                    'profit': profit,
                    'resultado': resultado_trade,
                    'capital': capital,
                    'razon': resultado['razon'][:50]
                }
                trades.append(trade)
                
                # Actualizar estado
                reportar_resulto(estado, resultado_trade == 'WIN')
                
                # Verificar límites diarios
                if profit_total >= target_diario:
                    print(f"\n¡Target diario alcanzado! Profit: ${profit_total:.2f}")
                    break
                elif capital <= capital_inicial - stop_diario:
                    print(f"\nStop diario alcanzado. Pérdida: ${abs(profit_total):.2f}")
                    break
    
    # Resultados
    total_trades = len(trades)
    winrate = (wins / total_trades * 100) if total_trades > 0 else 0
    
    print("\n=== RESULTADOS DE LA SIMULACIÓN ===")
    print(f"Capital inicial: ${capital_inicial:.2f}")
    print(f"Capital final: ${capital:.2f}")
    print(f"Profit total: ${profit_total:.2f}")
    print(f"Retorno: {(profit_total/capital_inicial*100):.2f}%")
    print(f"Total trades: {total_trades}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Winrate: {winrate:.2f}%")
    
    if total_trades > 0:
        # Mostrar últimos 10 trades
        print(f"\nÚltimos 10 trades:")
        for trade in trades[-10:]:
            print(f"  {trade['direccion']} {trade['resultado']} stake=${trade['stake']:.2f} profit=${trade['profit']:.2f} cap=${trade['capital']:.2f}")
        
        # Análisis por dirección
        calls = [t for t in trades if t['direccion'] == 'COMPRA']
        puts = [t for t in trades if t['direccion'] == 'VENTA']
        
        if calls:
            wins_calls = sum(1 for t in calls if t['resultado'] == 'WIN')
            winrate_calls = wins_calls/len(calls)*100
            print(f"\nCALLs: {len(calls)} trades, {wins_calls} wins, winrate {winrate_calls:.1f}%")
        
        if puts:
            wins_puts = sum(1 for t in puts if t['resultado'] == 'WIN')
            winrate_puts = wins_puts/len(puts)*100
            print(f"PUTs: {len(puts)} trades, {wins_puts} wins, winrate {winrate_puts:.1f}%")
    
    return trades

if __name__ == "__main__":
    simular_trades()