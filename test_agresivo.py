"""
Bot de Prueba - Estrategia Agresiva
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from estrategia_agresiva import EstadoAgresivo, evaluar_momentum_agresivo, reportar_resulto_agresivo
from gestion_riesgo.models import Cuenta, TickDerivHistorico

def test_estrategia_agresiva():
    print("=== TEST ESTRATEGIA AGRESIVA ===")
    print("Objetivo: Winrate >55%, 10% diario")
    
    capital_inicial = 100.0
    capital = capital_inicial
    target_diario = capital_inicial * 0.10
    
    # Obtener datos R_100
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        print("No se encontró cuenta R_100")
        return
    
    ticks = list(TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch'))
    print(f"Ticks R_100: {len(ticks)}")
    
    if len(ticks) < 500:
        print("No hay suficientes datos")
        return
    
    estado = EstadoAgresivo()
    trades = []
    wins = 0
    losses = 0
    
    print("\nIniciando trading...")
    
    for i in range(100, len(ticks)):
        precio = ticks[i].precio
        
        resultado = evaluar_momentum_agresivo(precio, estado, cooldown=2)
        
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
                    'capital': capital,
                    'razon': resultado['razon'][:50]
                })
                
                reportar_resulto_agresivo(estado, profit > 0)
                
                if capital - capital_inicial >= target_diario:
                    print(f"\n¡TARGET ALCANZADO! Profit: ${capital - capital_inicial:.2f}")
                    break
    
    # Resultados
    total = len(trades)
    winrate = (wins/total*100) if total > 0 else 0
    profit_total = capital - capital_inicial
    
    print(f"\n{'='*50}")
    print("RESULTADOS ESTRATEGIA AGRESIVA")
    print(f"{'='*50}")
    print(f"Capital final: ${capital:.2f}")
    print(f"Profit total: ${profit_total:.2f}")
    print(f"Retorno: {(profit_total/capital_inicial*100):.2f}%")
    print(f"Total trades: {total}")
    print(f"Winrate: {winrate:.1f}% ({wins}W/{losses}L)")
    
    if trades:
        print(f"\nÚltimos 10 trades:")
        for t in trades[-10:]:
            print(f"  {t['direccion']} {t['resultado']} stake=${t['stake']:.2f} profit=${t['profit']:.2f}")
    
    return winrate, profit_total

if __name__ == "__main__":
    test_estrategia_agresiva()