"""
BACKTEST COMPLETO: Winrate por horario

Simula operaciones basándose en la estrategia SPP (EMA gap + slope)
y calcula winrate/hora para identificar las mejores horas para operar.
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


def ema(prev, precio, periodo):
    alpha = 2.0 / (periodo + 1)
    return (precio * alpha) + (prev * (1 - alpha))


def slope(data, n=5):
    if len(data) < n + 1:
        return None
    prices = list(data)[-n-1:]
    n_vals = len(prices) - 1
    if n_vals == 0:
        return None
    dx = n_vals
    dy = prices[-1] - prices[0]
    return dy / dx


def backtest_por_hora(precios, epochs, params):
    """
    Backtest simple: EMA gap + slope threshold.
    Devuelve estadísticas por hora UTC.
    """
    ema_fast = params['ema_fast']
    ema_slow = params['ema_slow']
    min_gap = params['min_gap']
    slope_th = params['slope_threshold']
    cooldown = params['cooldown']
    duracion = params['duracion']
    
    ef = None
    es = None
    ef_hist = deque(maxlen=100)
    es_hist = deque(maxlen=100)
    
    capital = 100.0
    cooldown_restante = 0
    
    # Por hora UTC
    stats_por_hora = {h: {'wins': 0, 'losses': 0, 'total': 0, 'profit': 0} for h in range(24)}
    
    for i in range(len(precios)):
        p = float(precios[i])
        ep = int(epochs[i])
        
        # Actualizar EMAs
        if ef is None:
            ef = p
            es = p
        else:
            ef = ema(ef, p, ema_fast)
            es = ema(es, p, ema_slow)
        
        ef_hist.append(ef)
        es_hist.append(es)
        
        # Cooldown
        if cooldown_restante > 0:
            cooldown_restante -= 1
            continue
        
        # Calentar
        if len(ef_hist) < ema_slow + 10:
            continue
        
        # Hora UTC
        hora = datetime.fromtimestamp(ep, tz=timezone.utc).hour
        
        # Gap y slope
        gap = abs(ef - es)
        slp = slope(ef_hist, 5)
        
        # Señal
        if gap >= min_gap:
            if ef > es and slp is not None and slp > slope_th:
                # CALL
                if i + duracion < len(precios):
                    salida = float(precios[i + duracion])
                    ganancia = 0.85 if salida > p else -1.0
                else:
                    ganancia = 0
                
                capital += ganancia
                stats_por_hora[hora]['total'] += 1
                stats_por_hora[hora]['profit'] += ganancia
                if ganancia > 0:
                    stats_por_hora[hora]['wins'] += 1
                else:
                    stats_por_hora[hora]['losses'] += 1
                
                cooldown_restante = cooldown
    
    return stats_por_hora


def main():
    print("=" * 80)
    print("BACKTEST: WINRATE POR HORA UTC")
    print("=" * 80)
    
    # Cargar datos
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        print("ERROR: No existe cuenta R_100")
        return
    
    ticks = TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch')
    precios = [float(t.precio) for t in ticks]
    epochs = [int(t.epoch) for t in ticks]
    
    print(f"\nTicks cargados: {len(precios)}")
    
    # Rango temporal
    from_dt = datetime.fromtimestamp(epochs[0], tz=timezone.utc)
    to_dt = datetime.fromtimestamp(epochs[-1], tz=timezone.utc)
    print(f"Desde: {from_dt.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Hasta: {to_dt.strftime('%Y-%m-%d %H:%M')} UTC")
    
    # Configuración a probar
    configs = [
        {'name': 'EMA 5/13, gap>0.30, slope>0.30, dur=10', 'ema_fast': 5, 'ema_slow': 13, 'min_gap': 0.30, 'slope_threshold': 0.30, 'cooldown': 5, 'duracion': 10},
        {'name': 'EMA 5/13, gap>0.25, slope>0.20, dur=15', 'ema_fast': 5, 'ema_slow': 13, 'min_gap': 0.25, 'slope_threshold': 0.20, 'cooldown': 5, 'duracion': 15},
        {'name': 'EMA 5/13, gap>0.20, slope>0.15, dur=20', 'ema_fast': 5, 'ema_slow': 13, 'min_gap': 0.20, 'slope_threshold': 0.15, 'cooldown': 5, 'duracion': 20},
        {'name': 'EMA 8/21, gap>0.30, slope>0.25, dur=15', 'ema_fast': 8, 'ema_slow': 21, 'min_gap': 0.30, 'slope_threshold': 0.25, 'cooldown': 5, 'duracion': 15},
    ]
    
    breakeven = 100 / (1 + 0.85)  # ~54.05%
    print(f"\nBreakeven: {breakeven:.2f}%")
    
    # Probar cada configuración
    for config in configs:
        print(f"\n{'='*80}")
        print(f"CONFIG: {config['name']}")
        print(f"{'='*80}")
        
        stats = backtest_por_hora(precios, epochs, config)
        
        # Filtrar horas con suficientes datos
        horas_validas = []
        for h in range(24):
            s = stats[h]
            if s['total'] >= 5:  # Mínimo 5 trades
                wr = (s['wins'] / s['total'] * 100) if s['total'] > 0 else 0
                edge = wr - breakeven
                horas_validas.append({
                    'hora': h,
                    'total': s['total'],
                    'wins': s['wins'],
                    'losses': s['losses'],
                    'wr': wr,
                    'edge': edge,
                    'profit': s['profit'],
                })
        
        if not horas_validas:
            print("  No hay horas con suficientes datos (>5 trades)")
            continue
        
        # Ordenar por winrate
        horas_validas.sort(key=lambda x: x['wr'], reverse=True)
        
        print(f"\n  {'HORA':<6} {'TRADES':<8} {'W/L':<10} {'WR':<8} {'EDGE':<8} {'PROFIT':<10} {'STATUS'}")
        print(f"  {'-'*70}")
        
        for h in horas_validas:
            status = "*** SUPERADO ***" if h['edge'] > 10 else "OK" if h['edge'] > 0 else "BAJO" if h['edge'] > -10 else "MUY BAJO"
            h_col = (h['hora'] - 5) % 24  # Colombia UTC-5
            print(f"  {h['hora']:02d}:00 UTC ({h_col:02d}:00 COL) {h['total']:>5}    {h['wins']}/{h['losses']:<6} {h['wr']:>5.1f}%  {h['edge']:>+5.1f}%  ${h['profit']:>+7.2f}  {status}")
        
        # Resumen
        mejores = [h for h in horas_validas if h['edge'] > 10]
        buenos = [h for h in horas_validas if 0 < h['edge'] <= 10]
        
        print(f"\n  RESUMEN:")
        if mejores:
            print(f"    MEJORES HORAS (edge >10%): {', '.join(f'{h['hora']:02d}:00' for h in mejores)}")
        if buenos:
            print(f"    BUENAS HORAS (edge 0-10%): {', '.join(f'{h['hora']:02d}:00' for h in buenos)}")
        
        # Equivalentes en Colombia
        print(f"\n  EN COLOMBIA (UTC-5):")
        todas = sorted(horas_validas, key=lambda x: x['hora'])
        for h in todas:
            h_col = (h['hora'] - 5) % 24
            print(f"    {h_col:02d}:00 COL = {h['hora']:02d}:00 UTC  |  {h['total']} trades  |  WR: {h['wr']:.1f}%  |  ${h['profit']:+.2f}")
    
    print(f"\n{'='*80}")
    print("FIN DEL BACKTEST")
    print("=" * 80)


if __name__ == "__main__":
    main()
