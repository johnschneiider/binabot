"""
Test de la estrategia mejorada
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from estrategia_mejorada import EstadoMejorado, evaluar_estrategia_mejorada, reportar_resulto_mejorado
from gestion_riesgo.models import Cuenta, TickDerivHistorico

def test_estrategia_mejorada():
    print("=== TEST ESTRATEGIA MEJORADA ===")
    print("Objetivo: Winrate >60%, 10% diario")
    
    capital_inicial = 100.0
    capital = capital_inicial
    target_diario = capital_inicial * 0.10
    stop_diario = capital_inicial * 0.05
    
    # Probar con R_100
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        print("No se encontró cuenta R_100")
        return
    
    ticks = list(TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch'))
    print(f"Ticks R_100: {len(ticks)}")
    
    if len(ticks) < 500:
        return
    
    estado = EstadoMejorado()
    trades = []
    wins = 0
    losses = 0
    
    print("\nIniciando trading...")
    
    for i in range(150, len(ticks)):
        precio = ticks[i].precio
        
        resultado = evaluar_estrategia_mejorada(precio, estado, cooldown=4)
        
        if resultado['decision'] in ['COMPRA', 'VENTA']:
            stake = resultado['stake']
            
            if i + 5 < len(ticks):
                precio_entrada = precio
                precio_salida = ticks[i + 5].precio
                
                if resultado['decision'] == 'COMPRA':
                    if precio_salida > precio_entrada:
                        profit = stake * 0.85
                        wins += 1
                    else:
                        profit = -stake
                        losses += 1
                else:
                    if precio_salida < precio_entrada:
                        profit = stake * 0.85
                        wins += 1
                    else:
                        profit = -stake
                        losses += 1
                
                capital += profit
                trades.append({
                    'direccion': resultado['decision'],
                    'stake': stake,
                    'profit': profit,
                    'resultado': 'WIN' if profit > 0 else 'LOSS',
                    'capital': capital
                })
                
                reportar_resulto_mejorado(estado, profit > 0)
                
                if capital - capital_inicial >= target_diario:
                    print(f"\n¡TARGET ALCANZADO! Profit: ${capital - capital_inicial:.2f}")
                    break
                
                if capital <= capital_inicial - stop_diario:
                    print(f"\nStop loss alcanzado. Pérdida: ${abs(capital - capital_inicial):.2f}")
                    break
    
    total = len(trades)
    winrate = (wins/total*100) if total > 0 else 0
    profit_total = capital - capital_inicial
    
    print(f"\n{'='*50}")
    print("RESULTADOS ESTRATEGIA MEJORADA")
    print(f"{'='*50}")
    print(f"Capital final: ${capital:.2f}")
    print(f"Profit total: ${profit_total:.2f}")
    print(f"Retorno: {(profit_total/capital_inicial*100):.2f}%")
    print(f"Total trades: {total}")
    print(f"Winrate: {winrate:.1f}% ({wins}W/{losses}L)")
    
    if trades:
        # Análisis por tipo
        calls = [t for t in trades if t['direccion'] == 'COMPRA']
        puts = [t for t in trades if t['direccion'] == 'VENTA']
        
        if calls:
            calls_wins = sum(1 for t in calls if t['resultado'] == 'WIN')
            print(f"\nCALLs: {len(calls)} trades, {calls_wins} wins, winrate {calls_wins/len(calls)*100:.1f}%")
        
        if puts:
            puts_wins = sum(1 for t in puts if t['resultado'] == 'WIN')
            print(f"PUTs: {len(puts)} trades, {puts_wins} wins, winrate {puts_wins/len(puts)*100:.1f}%")
        
        print(f"\nÚltimos 10 trades:")
        for t in trades[-10:]:
            print(f"  {t['direccion']} {t['resultado']} stake=${t['stake']:.2f} profit=${t['profit']:.2f} cap=${t['capital']:.2f}")
    
    return winrate, profit_total

if __name__ == "__main__":
    test_estrategia_mejorada()