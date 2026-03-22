"""
Backtesting de la estrategia Momentum Breakout
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estrategia_momentum import EstadoMomentum, evaluar_momentum_breakout, reportar_resulto
import pandas as pd
import numpy as np
from datetime import datetime

# Obtener datos históricos
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from gestion_riesgo.models import TickDerivHistorico, Cuenta

def backtest_momentum():
    print("=== BACKTESTING ESTRATEGIA MOMENTUM BREAKOUT ===")
    
    # Obtener ticks para R_10
    cuenta = Cuenta.objects.filter(simbolo='R_10').first()
    if not cuenta:
        print("No se encontró cuenta R_10")
        return
    
    ticks = TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch')
    print(f"Total ticks: {ticks.count()}")
    
    if ticks.count() < 1000:
        print("No hay suficientes datos")
        return
    
    # Convertir a DataFrame
    data = []
    for tick in ticks:
        data.append({
            'epoch': tick.epoch,
            'precio': tick.precio
        })
    
    df = pd.DataFrame(data)
    df = df.sort_values('epoch').reset_index(drop=True)
    
    # Parámetros de la estrategia (optimizados para más señales)
    params = {
        'momentum_ventana': 10,
        'volatilidad_ventana': 20,
        'rsi_periodo': 14,
        'ema_rapida': 9,
        'ema_lenta': 21,
        'umbral_momentum': 0.0001,
        'umbral_volatilidad': 0.0003,
        'umbral_rsi_sobrecompra': 70,
        'umbral_rsi_sobreventa': 30,
        'cooldown_ticks': 3,
        'stake_base': 1.0,
        'max_stake': 2.0
    }
    
    # Simulación
    estado = EstadoMomentum()
    capital = 100.0
    trades = []
    wins = 0
    losses = 0
    
    print("\nParámetros de la estrategia:")
    for k, v in params.items():
        print(f"  {k}: {v}")
    
    print("\nIniciando simulación...")
    
    for i in range(len(df)):
        precio = df.iloc[i]['precio']
        epoch = df.iloc[i]['epoch']
        
        # Evaluar señal
        senal = evaluar_momentum_breakout(precio, estado, **params)
        
        if senal['decision'] in ['COMPRA', 'VENTA']:
            # Simular trade (asumimos 5 ticks de duración)
            stake = senal['stake']
            
            # Obtener precio de salida (5 ticks después)
            if i + 5 < len(df):
                precio_salida = df.iloc[i + 5]['precio']
                
                # Determinar resultado
                if senal['decision'] == 'COMPRA':
                    # CALL: gana si precio sube
                    ganancia = stake * 0.85 if precio_salida > precio else -stake
                else:  # VENTA
                    # PUT: gana si precio baja
                    ganancia = stake * 0.85 if precio_salida < precio else -stake
                
                # Actualizar capital
                capital += ganancia
                
                # Registrar trade
                trade = {
                    'epoch_entrada': epoch,
                    'precio_entrada': precio,
                    'precio_salida': precio_salida,
                    'direccion': senal['decision'],
                    'stake': stake,
                    'ganancia': ganancia,
                    'capital': capital,
                    'razon': senal['razon'],
                    'confidence': senal['confidence']
                }
                trades.append(trade)
                
                # Actualizar estado
                fue_ganancia = ganancia > 0
                reportar_resulto(estado, fue_ganancia)
                
                if fue_ganancia:
                    wins += 1
                else:
                    losses += 1
    
    # Resultados
    total_trades = len(trades)
    winrate = (wins / total_trades * 100) if total_trades > 0 else 0
    profit_total = capital - 100.0
    
    print("\n=== RESULTADOS DEL BACKTEST ===")
    print(f"Capital inicial: $100.00")
    print(f"Capital final: ${capital:.2f}")
    print(f"Profit total: ${profit_total:.2f}")
    print(f"Retorno: {(profit_total/100*100):.2f}%")
    print(f"Total trades: {total_trades}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Winrate: {winrate:.2f}%")
    
    if total_trades > 0:
        # Análisis por dirección
        calls = [t for t in trades if t['direccion'] == 'COMPRA']
        puts = [t for t in trades if t['direccion'] == 'VENTA']
        
        print(f"\nAnálisis por dirección:")
        print(f"  CALL: {len(calls)} trades, {sum(1 for t in calls if t['ganancia']>0)} wins")
        print(f"  PUT: {len(puts)} trades, {sum(1 for t in puts if t['ganancia']>0)} wins")
        
        # Análisis por confianza
        high_conf = [t for t in trades if t['confidence'] > 0.7]
        med_conf = [t for t in trades if 0.4 <= t['confidence'] <= 0.7]
        low_conf = [t for t in trades if t['confidence'] < 0.4]
        
        print(f"\nAnálisis por confianza:")
        for grupo, nombre in [(high_conf, 'Alta (>0.7)'), (med_conf, 'Media (0.4-0.7)'), (low_conf, 'Baja (<0.4)')]:
            if grupo:
                wins_grupo = sum(1 for t in grupo if t['ganancia']>0)
                winrate_grupo = wins_grupo/len(grupo)*100
                profit_grupo = sum(t['ganancia'] for t in grupo)
                print(f"  {nombre}: {len(grupo)} trades, winrate {winrate_grupo:.1f}%, profit ${profit_grupo:.2f}")
        
        # Mostrar últimos trades
        print(f"\nÚltimos 10 trades:")
        for trade in trades[-10:]:
            resultado = "WIN" if trade['ganancia'] > 0 else "LOSS"
            print(f"  {trade['direccion']} {resultado} stake=${trade['stake']:.2f} profit=${trade['ganancia']:.2f} cap=${trade['capital']:.2f}")
    
    # Guardar resultados
    trades_df = pd.DataFrame(trades)
    trades_df.to_csv('backtest_results.csv', index=False)
    print(f"\nResultados guardados en backtest_results.csv")
    
    return trades_df

if __name__ == "__main__":
    backtest_momentum()