"""
Backtest realista para estrategia simple - Evita sobreajuste
Usa solo 1 parámetro: hora boa (22h UTC)
Sin optimización de múltiples parámetros
"""

import os
import sys
from datetime import datetime, timezone
from collections import deque

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import TickDerivHistorico, Cuenta
from vector_pesos.senal_spp import _alpha, _slope


def backtest_simple(precios, epochs, hora_utc_boa=22, duracion=10):
    """
    Estrategia ultra-simple: Solo EMA gap + hora boa
    Sin filtros ADX, ATR, Choppy, RSI
    """
    ema_fast_val = None
    ema_slow_val = None
    ema_fast_hist = deque(maxlen=64)
    
    capital = 100.0
    trades = []
    wins = 0
    losses = 0
    cooldown = 0
    
    min_gap = 0.30  # Fijo según backtest histórico
    
    for i in range(len(precios)):
        precio = float(precios[i])
        epoch = epochs[i]
        
        # Actualizar EMAs
        if ema_fast_val is None:
            ema_fast_val = precio
            ema_slow_val = precio
        else:
            ema_fast_val = precio * _alpha(5) + ema_fast_val * (1 - _alpha(5))
            ema_slow_val = precio * _alpha(13) + ema_slow_val * (1 - _alpha(13))
        
        ema_fast_hist.append(ema_fast_val)
        
        # Cooldown
        if cooldown > 0:
            cooldown -= 1
            continue
        
        # Solo operar en hora boa
        try:
            hora = datetime.fromtimestamp(int(epoch), tz=timezone.utc).hour
            if hora != hora_utc_boa:
                continue
        except:
            continue
        
        # Calentar
        if len(ema_fast_hist) < 20:
            continue
        
        # Señal simple
        ema_gap = abs(ema_fast_val - ema_slow_val)
        
        if ema_gap >= min_gap:
            if ema_fast_val > ema_slow_val:
                # CALL
                if i + duracion < len(precios):
                    salida = precios[i + duracion]
                    ganancia = 0.85 if salida > precio else -1.0
                else:
                    ganancia = 0
                
                capital += ganancia
                trades.append({'hora': hora, 'dir': 'CALL', 'ganancia': ganancia, 'gap': ema_gap})
                
                if ganancia > 0:
                    wins += 1
                else:
                    losses += 1
                
                cooldown = 5  # Reducido de 15 a 5
    
    total = len(trades)
    wr = (wins / total * 100) if total > 0 else 0
    breakeven = 54.05  # 1/(1+0.85)
    edge = wr - breakeven
    
    return {
        'trades': total,
        'wins': wins,
        'losses': losses,
        'winrate': wr,
        'breakeven': breakeven,
        'edge': edge,
        'profit': capital - 100,
        'capital': capital,
    }


def main():
    print("=" * 80)
    print("BACKTEST REALISTA - Hora Boa 22h UTC")
    print("=" * 80)
    
    # Cargar datos
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        print("ERROR: No existe cuenta R_100")
        return
    
    ticks = TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch')
    precios = [float(t.precio) for t in ticks]
    epochs = [int(t.epoch) for t in ticks]
    
    print(f"Total ticks: {len(precios)}")
    
    # Distribución por hora
    horas = {}
    for ep in epochs:
        h = datetime.fromtimestamp(ep, tz=timezone.utc).hour
        horas[h] = horas.get(h, 0) + 1
    
    print(f"\nDistribucion de ticks por hora UTC:")
    for h in sorted(horas.keys()):
        print(f"  {h:02d}: {horas[h]} ticks")
    
    # Testear varias duraciones
    print("\n" + "=" * 80)
    print("RESULTADOS POR DURACION (Hora Boa 22h UTC)")
    print("=" * 80)
    
    resultados = []
    for dur in [5, 10, 15, 20, 25]:
        r = backtest_simple(precios, epochs, hora_utc_boa=22, duracion=dur)
        r['duracion'] = dur
        resultados.append(r)
        
        mas = "+" if r['edge'] >= 0 else ""
        print(f"  dur={dur:2d}: WR={r['winrate']:5.1f}% | Trades={r['trades']:3d} | "
              f"Edge={mas}{r['edge']:5.1f}% | Profit=${r['profit']:+.2f}")
    
    # Mejor duración
    resultados.sort(key=lambda x: x['edge'], reverse=True)
    mejor = resultados[0]
    
    print("\n" + "=" * 80)
    print("RECOMENDACION")
    print("=" * 80)
    print(f"""
Hora boa: 22:00 UTC (17:00 Colombia)
Duracion recomendada: {mejor['duracion']} ticks
Winrate esperado: {mejor['winrate']:.1f}%
Edge sobre breakeven: {mejor['edge']:+.1f}%
Trades minimos para confiar: 50

CONFIGURACION RECOMENDADA:
  DERIV_BLOQUEO_HORAS_LOCAL=0-16,18-24  (solo 17 Colombia = 22 UTC)
  DERIV_DURACION_TICKS={mejor['duracion']}
  SPP_COOLDOWN_TICKS=5
  SPP_EMA_FAST=5
  SPP_EMA_SLOW=13
  SPP_MIN_EMA_GAP_R100=0.30
  
ADVERTENCIA:
  - Necesitas minimo 50 trades en demo para validar
  - Si WR < 54% (breakeven), NO operar real
  - Si WR > 60% con 50+ trades, confianza alta
""")


if __name__ == "__main__":
    main()
