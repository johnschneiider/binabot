"""
Test rápido de la estrategia Momentum en tiempo real
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from estrategia_momentum import EstadoMomentum, evaluar_momentum_breakout
from estrategia_config import MOMENTUM_PARAMS
from gestion_riesgo.models import TickDerivHistorico, Cuenta
import time

def test_momentum_real():
    print("=== TEST MOMENTUM EN TIEMPO REAL ===")
    
    # Obtener cuenta R_10
    cuenta = Cuenta.objects.filter(simbolo='R_10').first()
    if not cuenta:
        print("No se encontró cuenta R_10")
        return
    
    # Obtener últimos 500 ticks
    ticks = TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('-epoch')[:500]
    ticks = list(reversed(ticks))  # Orden cronológico
    
    print(f"Ticks obtenidos: {len(ticks)}")
    
    if len(ticks) < 100:
        print("No hay suficientes datos")
        return
    
    # Crear estado
    estado = EstadoMomentum()
    
    # Procesar ticks
    señales = 0
    for i, tick in enumerate(ticks):
        precio = tick.precio
        
        # Evaluar
        resultado = evaluar_momentum_breakout(precio, estado, **MOMENTUM_PARAMS)
        
        if resultado['decision'] in ['COMPRA', 'VENTA']:
            señales += 1
            print(f"Tick {i}: {resultado['decision']} - {resultado['razon']}")
            print(f"  Stake: ${resultado['stake']:.2f}, Confidence: {resultado['confidence']:.2f}")
            
            if 'indicadores' in resultado:
                ind = resultado['indicadores']
                print(f"  Indicadores: momentum={ind['momentum']:.8f}, volatilidad={ind['volatilidad']:.8f}, rsi={ind['rsi']:.1f}")
    
    print(f"\nTotal señales generadas: {señales}")
    print(f"Total ticks procesados: {len(ticks)}")
    print(f"Ratio señales/ticks: {señales/len(ticks)*100:.2f}%")

if __name__ == "__main__":
    test_momentum_real()