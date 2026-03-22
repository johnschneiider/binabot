"""
Estrategia simplificada para debugging
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estrategia_momentum import EstadoMomentum, evaluar_momentum_breakout
import pandas as pd

# Obtener datos históricos
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
import django
django.setup()

from gestion_riesgo.models import TickDerivHistorico, Cuenta

def test_estrategia():
    print("=== TEST ESTRATEGIA SIMPLIFICADA ===")
    
    # Obtener ticks para R_10
    cuenta = Cuenta.objects.filter(simbolo='R_10').first()
    if not cuenta:
        print("No se encontró cuenta R_10")
        return
    
    ticks = TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch')[:1000]
    print(f"Total ticks: {ticks.count()}")
    
    # Convertir a DataFrame
    data = []
    for tick in ticks:
        data.append({
            'epoch': tick.epoch,
            'precio': tick.precio
        })
    
    df = pd.DataFrame(data)
    df = df.sort_values('epoch').reset_index(drop=True)
    
    # Probar la estrategia en algunos puntos
    estado = EstadoMomentum()
    
    print("\nProbando estrategia...")
    
    for i in range(len(df)):
        precio = df.iloc[i]['precio']
        
        # Actualizar estado
        estado.precios.append(precio)
        
        if i % 100 == 0 and i > 100:
            print(f"\nTick {i}: precio={precio:.5f}")
            print(f"  Precios en estado: {len(estado.precios)}")
            
            # Probar evaluación
            params = {
                'momentum_ventana': 10,
                'volatilidad_ventana': 20,
                'rsi_periodo': 14,
                'ema_rapida': 9,
                'ema_lenta': 21,
                'umbral_momentum': 0.00001,  # Muy bajo para debugging
                'umbral_volatilidad': 0.00001,
                'umbral_rsi_sobrecompra': 70,
                'umbral_rsi_sobreventa': 30,
                'cooldown_ticks': 1,
                'stake_base': 1.0,
                'max_stake': 2.0
            }
            
            senal = evaluar_momentum_breakout(precio, estado, **params)
            
            print(f"  Señal: {senal['decision']}")
            print(f"  Razón: {senal['razon']}")
            
            if 'indicadores' in senal:
                ind = senal['indicadores']
                print(f"  Indicadores: momentum={ind['momentum']:.8f}, volatilidad={ind['volatilidad']:.8f}, rsi={ind['rsi']:.1f}")
                print(f"  EMAs: rápida={ind['ema_rapida']:.5f}, lenta={ind['ema_lenta']:.5f}, tendencia={ind['tendencia']}")

if __name__ == "__main__":
    test_estrategia()