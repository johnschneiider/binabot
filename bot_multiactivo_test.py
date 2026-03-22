"""
Bot Multi-Activo Simplificado para Pruebas
Usa R_100, Volatility 75 y R_10
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from estrategia_multiactivo import EstadoMultiActivo, evaluar_multi_activo, reportar_resulto_multi, CONFIGS_POR_ACTIVO
from gestion_riesgo.models import Cuenta, OperacionDeriv, TickDerivHistorico
import time

def simular_multiactivo():
    print("=== SIMULACIÓN MULTI-ACTIVO ===")
    print("Activos: R_100, Volatility 75, R_10")
    print("Objetivo: 10% diario con winrate >60%")
    
    # Configuración
    capital_inicial = 100.0
    capital = capital_inicial
    target_diario = capital_inicial * 0.10
    stop_diario = capital_inicial * 0.05
    
    print(f"\nCapital inicial: ${capital_inicial:.2f}")
    print(f"Target diario: ${target_diario:.2f}")
    print(f"Stop diario: ${stop_diario:.2f}")
    
    # Obtener datos para cada activo
    activos_data = {}
    for simbolo in ['R_100', 'R_10']:
        cuenta = Cuenta.objects.filter(simbolo=simbolo).first()
        if cuenta:
            ticks = list(TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch'))
            if len(ticks) > 500:
                activos_data[simbolo] = ticks
                print(f"  {simbolo}: {len(ticks)} ticks disponibles")
    
    if not activos_data:
        print("No hay datos suficientes")
        return
    
    # Simular trading multi-activo
    estado = EstadoMultiActivo()
    trades = []
    wins = 0
    losses = 0
    trades_por_activo = {}
    
    print("\nIniciando simulación...")
    
    # Usar el activo con más datos
    activo_principal = max(activos_data.keys(), key=lambda x: len(activos_data[x]))
    ticks_principales = activos_data[activo_principal]
    
    for i in range(100, len(ticks_principales)):
        tick = ticks_principales[i]
        precio = tick.precio
        
        # Evaluar para activo principal con config más sensible
        config = CONFIGS_POR_ACTIVO.get(activo_principal, CONFIGS_POR_ACTIVO['R_100']).copy()
        # Ajustar para ser más sensible
        config['umbral_fuerza_tendencia'] = 0.000005
        config['umbral_volatilidad_min'] = 0.000005
        config['cooldown_minimo'] = 2
        config['rsi_sobrecompra'] = 75
        config['rsi_sobreventa'] = 25
        
        resultado = evaluar_multi_activo(activo_principal, precio, estado, config=config)
        
        if resultado['decision'] in ['COMPRA', 'VENTA']:
            stake = resultado['stake']
            
            # Simular trade de 5 ticks
            if i + 5 < len(ticks_principales):
                precio_entrada = precio
                precio_salida = ticks_principales[i + 5].precio
                
                # Determinar resultado
                if resultado['decision'] == 'COMPRA':
                    if precio_salida > precio_entrada:
                        profit = stake * 0.85
                        resultado_trade = 'WIN'
                        wins += 1
                    else:
                        profit = -stake
                        resultado_trade = 'LOSS'
                        losses += 1
                else:  # VENTA
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
                
                # Registrar trade
                trade = {
                    'activo': activo_principal,
                    'tick': i,
                    'direccion': resultado['decision'],
                    'stake': stake,
                    'profit': profit,
                    'resultado': resultado_trade,
                    'capital': capital,
                    'razon': resultado['razon'][:60],
                    'confidence': resultado['confidence']
                }
                trades.append(trade)
                
                # Contar por activo
                trades_por_activo[activo_principal] = trades_por_activo.get(activo_principal, 0) + 1
                
                # Actualizar estado
                reportar_resulto_multi(estado, activo_principal, resultado_trade == 'WIN')
                
                # Verificar límites
                if capital - capital_inicial >= target_diario:
                    print(f"\n¡Target diario alcanzado! Profit: ${capital - capital_inicial:.2f}")
                    break
                elif capital <= capital_inicial - stop_diario:
                    print(f"\nStop diario alcanzado. Pérdida: ${abs(capital - capital_inicial):.2f}")
                    break
    
    # Resultados
    total_trades = len(trades)
    winrate = (wins / total_trades * 100) if total_trades > 0 else 0
    profit_total = capital - capital_inicial
    
    print(f"\n{'='*50}")
    print("RESULTADOS DE SIMULACIÓN MULTI-ACTIVO")
    print(f"{'='*50}")
    print(f"Capital inicial: ${capital_inicial:.2f}")
    print(f"Capital final: ${capital:.2f}")
    print(f"Profit total: ${profit_total:.2f}")
    print(f"Retorno: {(profit_total/capital_inicial*100):.2f}%")
    print(f"Total trades: {total_trades}")
    print(f"Wins: {wins}")
    print(f"Losses: {losses}")
    print(f"Winrate: {winrate:.2f}%")
    
    # Análisis por activo
    print(f"\nTrades por activo:")
    for activo, count in trades_por_activo.items():
        activo_trades = [t for t in trades if t['activo'] == activo]
        activo_wins = sum(1 for t in activo_trades if t['resultado'] == 'WIN')
        activo_winrate = (activo_wins / count * 100) if count > 0 else 0
        activo_profit = sum(t['profit'] for t in activo_trades)
        print(f"  {activo}: {count} trades, {activo_wins} wins, winrate {activo_winrate:.1f}%, profit ${activo_profit:.2f}")
    
    # Últimos trades
    if trades:
        print(f"\nÚltimos 10 trades:")
        for trade in trades[-10:]:
            print(f"  {trade['activo']} {trade['direccion']} {trade['resultado']} stake=${trade['stake']:.2f} profit=${trade['profit']:.2f} conf={trade['confidence']:.2f}")
    
    # Estadísticas de confianza
    high_conf = [t for t in trades if t['confidence'] > 0.7]
    med_conf = [t for t in trades if 0.4 <= t['confidence'] <= 0.7]
    low_conf = [t for t in trades if t['confidence'] < 0.4]
    
    print(f"\nAnálisis por confianza:")
    for grupo, nombre in [(high_conf, 'Alta (>0.7)'), (med_conf, 'Media (0.4-0.7)'), (low_conf, 'Baja (<0.4)')]:
        if grupo:
            wins_grupo = sum(1 for t in grupo if t['resultado'] == 'WIN')
            winrate_grupo = wins_grupo/len(grupo)*100
            profit_grupo = sum(t['profit'] for t in grupo)
            print(f"  {nombre}: {len(grupo)} trades, winrate {winrate_grupo:.1f}%, profit ${profit_grupo:.2f}")
    
    return trades

if __name__ == "__main__":
    simular_multiactivo()