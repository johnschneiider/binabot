"""
Backtest rápido para la Estrategia SPP (Structure + Slope + Pullback)
Prueba configuraciones específicas sin fuerza bruta excesiva.
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


def ema_incremental(prev: float, precio: float, periodo: int) -> float:
    return (precio * _alpha(periodo)) + (prev * (1 - _alpha(periodo)))


def backtest_spp_fast(precios: list, epochs: list, config: dict) -> dict:
    """Backtest rápido con configuración específica."""
    ema_fast = config['ema_fast']
    ema_slow = config['ema_slow']
    slope_n = config['slope_n']
    min_gap = config['min_gap']
    slope_threshold = config['slope_threshold']
    cooldown_ticks = config['cooldown_ticks']
    duracion_ticks = config['duracion_ticks']
    horas_permitidas = config.get('horas', [19, 22, 23])
    solo_calls = config.get('solo_calls', True)
    payout = config.get('payout', 0.85)
    min_stake = config.get('min_stake', 1.0)
    
    ema_fast_val = None
    ema_slow_val = None
    ema_fast_hist = deque(maxlen=64)
    ema_slow_hist = deque(maxlen=64)
    
    capital = 100.0
    trades = []
    wins = 0
    losses = 0
    cooldown_restante = 0
    
    for i in range(len(precios)):
        precio = float(precios[i])
        epoch = epochs[i]
        
        # Actualizar EMAs
        if ema_fast_val is None:
            ema_fast_val = precio
            ema_slow_val = precio
        else:
            ema_fast_val = ema_incremental(ema_fast_val, precio, ema_fast)
            ema_slow_val = ema_incremental(ema_slow_val, precio, ema_slow)
        
        ema_fast_hist.append(ema_fast_val)
        ema_slow_hist.append(ema_slow_val)
        
        # Cooldown
        if cooldown_restante > 0:
            cooldown_restante -= 1
            continue
        
        # Verificar hora
        try:
            hora_utc = datetime.fromtimestamp(int(epoch), tz=timezone.utc).hour
            if hora_utc not in horas_permitidas:
                continue
        except Exception:
            pass
        
        # Calentar
        if len(ema_fast_hist) < ema_slow + slope_n:
            continue
        
        # Gap y slope
        ema_gap = abs(ema_fast_val - ema_slow_val)
        slope_val = _slope(ema_fast_hist, slope_n)
        
        # Bias
        if ema_fast_val > ema_slow_val:
            bias = "CALL"
        elif ema_fast_val < ema_slow_val:
            bias = "PUT"
        else:
            continue
        
        # Señal
        if bias == "CALL" and ema_gap >= min_gap:
            if slope_val is not None and slope_val > slope_threshold:
                # Operar CALL
                if i + duracion_ticks < len(precios):
                    precio_salida = precios[i + duracion_ticks]
                    ganancia = min_stake * payout if precio_salida > precio else -min_stake
                else:
                    ganancia = 0
                
                capital += ganancia
                trades.append({
                    'hora': hora_utc,
                    'precio_entrada': precio,
                    'precio_salida': precio_salida,
                    'direccion': 'CALL',
                    'ganancia': ganancia,
                    'capital': capital,
                    'ema_gap': ema_gap,
                    'slope': slope_val,
                })
                
                if ganancia > 0:
                    wins += 1
                else:
                    losses += 1
                
                cooldown_restante = cooldown_ticks
        
        elif bias == "PUT" and ema_gap >= min_gap and not solo_calls:
            if slope_val is not None and slope_val < -slope_threshold:
                if i + duracion_ticks < len(precios):
                    precio_salida = precios[i + duracion_ticks]
                    ganancia = min_stake * payout if precio_salida < precio else -min_stake
                else:
                    ganancia = 0
                
                capital += ganancia
                trades.append({
                    'hora': hora_utc,
                    'precio_entrada': precio,
                    'precio_salida': precio_salida,
                    'direccion': 'PUT',
                    'ganancia': ganancia,
                    'capital': capital,
                    'ema_gap': ema_gap,
                    'slope': slope_val,
                })
                
                if ganancia > 0:
                    wins += 1
                else:
                    losses += 1
                
                cooldown_restante = cooldown_ticks
    
    total = len(trades)
    winrate = (wins / total * 100) if total > 0 else 0
    breakeven = 100 / (1 + payout)
    edge = winrate - breakeven
    
    return {
        'trades': trades,
        'wins': wins,
        'losses': losses,
        'total': total,
        'winrate': winrate,
        'profit': capital - 100,
        'capital_final': capital,
        'breakeven': breakeven,
        'edge': edge,
        'params': config.copy(),
    }


def main():
    print("=" * 80)
    print("BACKTEST RAPIDO ESTRATEGIA SPP - R_100")
    print("=" * 80)
    
    # Cargar datos
    cuenta = Cuenta.objects.filter(simbolo='R_100').first()
    if not cuenta:
        print("ERROR: No existe cuenta R_100")
        return
    
    ticks = TickDerivHistorico.objects.filter(cuenta=cuenta).order_by('epoch')
    total_ticks = ticks.count()
    print(f"\nTotal ticks históricos: {total_ticks}")
    
    if total_ticks < 1000:
        print("ERROR: No hay suficientes datos")
        return
    
    precios = []
    epochs = []
    for tick in ticks:
        precios.append(float(tick.precio))
        epochs.append(int(tick.epoch))
    
    # Rango temporal
    from_dt = datetime.fromtimestamp(epochs[0], tz=timezone.utc)
    to_dt = datetime.fromtimestamp(epochs[-1], tz=timezone.utc)
    print(f"Rango: {from_dt.strftime('%Y-%m-%d %H:%M')} UTC -> {to_dt.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Duracion: {(to_dt - from_dt).total_seconds() / 3600:.1f} horas")
    
    # Distribución por hora
    horas_dist = {}
    for ep in epochs:
        h = datetime.fromtimestamp(ep, tz=timezone.utc).hour
        horas_dist[h] = horas_dist.get(h, 0) + 1
    
    print("\nDistribucion de ticks por hora UTC:")
    for h in sorted(horas_dist.keys()):
        bar = "#" * (horas_dist[h] // 100)
        print(f"  {h:02d}:00 [{horas_dist[h]:5d}] {bar}")
    
    # Configuraciones a probar (las más prometedoras según teoría)
    configs = [
        # Basado en comentarios del .env - "EMA(5,13), gap>0.30, CALL-only, dur=20-25"
        {
            'name': 'EMA(5,13) gap0.30 dur25',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 7,
            'min_gap': 0.30, 'slope_threshold': 0.30,
            'cooldown_ticks': 10, 'duracion_ticks': 25,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) gap0.30 dur10',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 7,
            'min_gap': 0.30, 'slope_threshold': 0.30,
            'cooldown_ticks': 10, 'duracion_ticks': 10,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) gap0.25 dur15',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 5,
            'min_gap': 0.25, 'slope_threshold': 0.25,
            'cooldown_ticks': 15, 'duracion_ticks': 15,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(9,21) gap0.40 dur20',
            'ema_fast': 9, 'ema_slow': 21, 'slope_n': 7,
            'min_gap': 0.40, 'slope_threshold': 0.20,
            'cooldown_ticks': 20, 'duracion_ticks': 20,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) gap0.35 dur15 solo19h',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 5,
            'min_gap': 0.35, 'slope_threshold': 0.35,
            'cooldown_ticks': 15, 'duracion_ticks': 15,
            'horas': [19], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) gap0.40 dur10',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 5,
            'min_gap': 0.40, 'slope_threshold': 0.30,
            'cooldown_ticks': 10, 'duracion_ticks': 10,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(8,15) gap0.35 dur15',
            'ema_fast': 8, 'ema_slow': 15, 'slope_n': 5,
            'min_gap': 0.35, 'slope_threshold': 0.30,
            'cooldown_ticks': 15, 'duracion_ticks': 15,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(10,21) gap0.45 dur20',
            'ema_fast': 10, 'ema_slow': 21, 'slope_n': 7,
            'min_gap': 0.45, 'slope_threshold': 0.25,
            'cooldown_ticks': 20, 'duracion_ticks': 20,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) gap0.50 dur10 agresiva',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 3,
            'min_gap': 0.50, 'slope_threshold': 0.40,
            'cooldown_ticks': 5, 'duracion_ticks': 10,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) mas horas (18-23)',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 7,
            'min_gap': 0.30, 'slope_threshold': 0.30,
            'cooldown_ticks': 10, 'duracion_ticks': 25,
            'horas': [18, 19, 20, 21, 22, 23], 'solo_calls': True,
        },
        {
            'name': 'EMA(5,13) +PUT enabled',
            'ema_fast': 5, 'ema_slow': 13, 'slope_n': 7,
            'min_gap': 0.30, 'slope_threshold': 0.30,
            'cooldown_ticks': 15, 'duracion_ticks': 20,
            'horas': [19, 22, 23], 'solo_calls': False,
        },
        {
            'name': 'Relaxed: EMA(8,18) gap0.20 dur10',
            'ema_fast': 8, 'ema_slow': 18, 'slope_n': 5,
            'min_gap': 0.20, 'slope_threshold': 0.15,
            'cooldown_ticks': 10, 'duracion_ticks': 10,
            'horas': [19, 22, 23], 'solo_calls': True,
        },
    ]
    
    print("\n" + "=" * 80)
    print("RESULTADOS POR CONFIGURACIÓN")
    print("=" * 80)
    
    resultados = []
    
    for config in configs:
        result = backtest_spp_fast(precios, epochs, config)
        result['name'] = config['name']
        resultados.append(result)
        
        print(f"\n{config['name']}")
        print(f"  Trades: {result['total']:4d} | WR: {result['winrate']:5.1f}% | BE: {result['breakeven']:.1f}% | Edge: {result['edge']:+5.1f}%")
        print(f"  Profit: ${result['profit']:+.2f} | Capital: ${result['capital_final']:.2f}")
        
        if result['trades']:
            # Por hora
            by_hour = {}
            for t in result['trades']:
                h = t['hora']
                if h not in by_hour:
                    by_hour[h] = {'wins': 0, 'total': 0}
                by_hour[h]['total'] += 1
                if t['ganancia'] > 0:
                    by_hour[h]['wins'] += 1
            
            horas_str = []
            for h in sorted(by_hour.keys()):
                d = by_hour[h]
                wr = d['wins'] / d['total'] * 100 if d['total'] > 0 else 0
                horas_str.append(f"{h:02d}h:{wr:.0f}%({d['total']})")
            print(f"  Por hora: {', '.join(horas_str)}")
    
    # Ordenar por edge
    resultados.sort(key=lambda x: x['edge'], reverse=True)
    
    print("\n" + "=" * 80)
    print("TOP 5 CONFIGURACIONES (por Edge)")
    print("=" * 80)
    
    for i, r in enumerate(resultados[:5]):
        p = r['params']
        print(f"\n#{i+1} {r['name']}")
        print(f"   EDGE: {r['edge']:+.2f}% | WR: {r['winrate']:.1f}% | Trades: {r['total']}")
        print(f"   EMA({p['ema_fast']},{p['ema_slow']}) gap={p['min_gap']:.2f} slope>{p['slope_threshold']:.2f}")
        print(f"   cooldown={p['cooldown_ticks']} dur={p['duracion_ticks']} horas={p['horas']}")
        print(f"   Profit: ${r['profit']:.2f}")
    
    # Mejor configuración
    mejor = resultados[0]
    p = mejor['params']
    
    print("\n" + "=" * 80)
    print("CONFIGURACIÓN RECOMENDADA")
    print("=" * 80)
    
    print(f"""
WINRATE: {mejor['winrate']:.2f}% (breakeven = {mejor['breakeven']:.2f}%)
EDGE: {mejor['edge']:+.2f}% sobre breakeven
TRADES: {mejor['total']}
PROFIT: ${mejor['profit']:.2f}

PARÁMETROS PARA .env:
  SPP_EMA_FAST={p['ema_fast']}
  SPP_EMA_SLOW={p['ema_slow']}
  SPP_SLOPE_N={p['slope_n']}
  SPP_MIN_EMA_GAP_R100={p['min_gap']}
  SPP_SLOPE_THRESHOLD_R100={p['slope_threshold']}
  SPP_COOLDOWN_TICKS={p['cooldown_ticks']}
  DERIV_DURACION_TICKS={p['duracion_ticks']}
  
HORAS PERMITIDAS (UTC):
  {p['horas']}
""")
    
    return resultados


if __name__ == "__main__":
    resultados = main()
