"""
Backtest riguroso para la Estrategia SPP (Structure + Slope + Pullback)
Usa los 29K ticks históricos de R_100 para optimizar parámetros.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import TickDerivHistorico, Cuenta
from vector_pesos.senal_spp import EstadoSPP, evaluar_senal_spp, _alpha, _slope
from collections import deque


def _ema_incremental(prev_ema: float, precio: float, periodo: int) -> float:
    alpha = _alpha(periodo)
    return (alpha * precio) + ((1.0 - alpha) * prev_ema)


def backtest_spp(
    precios: list,
    epochs: list,
    ema_fast: int,
    ema_slow: int,
    slope_n: int,
    min_gap: float,
    slope_threshold: float,
    cooldown_ticks: int,
    duracion_ticks: int,
    horas_permitidas: list = None,
    solo_calls: bool = True,
    min_stake: float = 1.0,
    payout: float = 0.85,
) -> dict:
    """
    Backtest completo de la estrategia SPP.
    
    Returns:
        dict con: trades, wins, losses, winrate, profit, capital_final
    """
    if horas_permitidas is None:
        horas_permitidas = [19, 22, 23]  # UTC
    
    ema_fast_val = None
    ema_slow_val = None
    
    capital = 100.0
    trades = []
    wins = 0
    losses = 0
    cooldown_restante = 0
    ultimo_precio = None
    
    ema_fast_hist = []
    ema_slow_hist = []
    
    for i, (precio, epoch) in enumerate(zip(precios, epochs)):
        precio = float(precio)
        
        # Actualizar EMAs
        if ema_fast_val is None:
            ema_fast_val = precio
            ema_slow_val = precio
        else:
            ema_fast_val = _ema_incremental(ema_fast_val, precio, ema_fast)
            ema_slow_val = _ema_incremental(ema_slow_val, precio, ema_slow)
        
        ema_fast_hist.append(ema_fast_val)
        ema_slow_hist.append(ema_slow_val)
        
        # Decrementar cooldown
        if cooldown_restante > 0:
            cooldown_restante -= 1
            ultimo_precio = precio
            continue
        
        # Verificar hora permitida
        try:
            hora_utc = datetime.utcfromtimestamp(int(epoch)).hour
            if hora_utc not in horas_permitidas:
                ultimo_precio = precio
                continue
        except Exception:
            pass
        
        # Verificar mínimos de calentamiento
        if len(ema_fast_hist) < ema_slow:
            ultimo_precio = precio
            continue
        
        # Calcular gap y slope
        ema_gap = abs(ema_fast_val - ema_slow_val)
        slope_val = _slope(deque(ema_fast_hist), slope_n) if len(ema_fast_hist) > slope_n else None
        
        # Determinar bias
        if ema_fast_val > ema_slow_val:
            bias = "CALL"
        elif ema_fast_val < ema_slow_val:
            bias = "PUT"
        else:
            bias = None
        
        # Señal CALL
        if bias == "CALL" and ema_gap >= min_gap:
            if slope_val is not None and slope_val > slope_threshold:
                # OPERAR CALL
                stake = min_stake
                
                # Simular salida después de duracion_ticks
                if i + duracion_ticks < len(precios):
                    precio_salida = precios[i + duracion_ticks]
                    ganancia = stake * payout if precio_salida > precio else -stake
                else:
                    ganancia = 0  # No hay datos de salida
                
                capital += ganancia
                trades.append({
                    'epoch': epoch,
                    'hora': hora_utc if 'hora_utc' in dir() else 0,
                    'precio_entrada': precio,
                    'precio_salida': precio_salida if i + duracion_ticks < len(precios) else None,
                    'direccion': 'CALL',
                    'stake': stake,
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
        
        # Para PUT (si no está bloqueado)
        elif bias == "PUT" and ema_gap >= min_gap and not solo_calls:
            if slope_val is not None and slope_val < -slope_threshold:
                # OPERAR PUT
                stake = min_stake
                
                if i + duracion_ticks < len(precios):
                    precio_salida = precios[i + duracion_ticks]
                    ganancia = stake * payout if precio_salida < precio else -stake
                else:
                    ganancia = 0
                
                capital += ganancia
                trades.append({
                    'epoch': epoch,
                    'hora': hora_utc if 'hora_utc' in dir() else 0,
                    'precio_entrada': precio,
                    'precio_salida': precio_salida if i + duracion_ticks < len(precios) else None,
                    'direccion': 'PUT',
                    'stake': stake,
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
        
        ultimo_precio = precio
    
    total = len(trades)
    winrate = (wins / total * 100) if total > 0 else 0
    breakeven = 100 / (1 + payout)  # ~53.7% para payout 0.85
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
        'params': {
            'ema_fast': ema_fast,
            'ema_slow': ema_slow,
            'slope_n': slope_n,
            'min_gap': min_gap,
            'slope_threshold': slope_threshold,
            'cooldown_ticks': cooldown_ticks,
            'duracion_ticks': duracion_ticks,
            'horas': horas_permitidas,
            'solo_calls': solo_calls,
        }
    }


def analyze_by_hour(trades: list) -> dict:
    """Analiza performance por hora UTC."""
    by_hour = {}
    for t in trades:
        h = t.get('hora', 0)
        if h not in by_hour:
            by_hour[h] = {'wins': 0, 'losses': 0, 'trades': 0, 'profit': 0}
        by_hour[h]['trades'] += 1
        by_hour[h]['profit'] += t['ganancia']
        if t['ganancia'] > 0:
            by_hour[h]['wins'] += 1
        else:
            by_hour[h]['losses'] += 1
    
    for h, data in by_hour.items():
        total = data['wins'] + data['losses']
        data['winrate'] = (data['wins'] / total * 100) if total > 0 else 0
    
    return by_hour


def optimize_params(precios: list, epochs: list) -> dict:
    """Optimización de parámetros por fuerza bruta."""
    resultados = []
    
    ema_fast_options = [5, 8, 9, 10, 12, 13, 15]
    ema_slow_options = [13, 15, 18, 21, 25, 30]
    slope_n_options = [3, 5, 7, 10]
    gap_options = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
    slope_th_options = [0.10, 0.15, 0.20, 0.25, 0.30]
    cooldown_options = [5, 10, 15, 20, 30]
    duracion_options = [5, 10, 15, 20, 25]
    
    horas_opciones = [
        [19, 22, 23],
        [19, 22],
        [22, 23],
        [19, 20, 21, 22, 23],
        list(range(19, 24)),
    ]
    
    print("Iniciando optimización...")
    total_combos = (
        len(ema_fast_options) * len(ema_slow_options) * len(slope_n_options) *
        len(gap_options) * len(slope_th_options) * len(cooldown_options) *
        len(duracion_options) * len(horas_opciones)
    )
    print(f"Total combinaciones a probar: {total_combos}")
    
    combo = 0
    for ef in ema_fast_options:
        for es in ema_slow_options:
            if es <= ef:
                continue
            for sn in slope_n_options:
                for gap in gap_options:
                    for st in slope_th_options:
                        for cd in cooldown_options:
                            for dur in duracion_options:
                                for horas in horas_opciones:
                                    combo += 1
                                    if combo % 500 == 0:
                                        print(f"Progreso: {combo}/{total_combos} ({combo/total_combos*100:.1f}%)")
                                    
                                    result = backtest_spp(
                                        precios, epochs,
                                        ema_fast=ef,
                                        ema_slow=es,
                                        slope_n=sn,
                                        min_gap=gap,
                                        slope_threshold=st,
                                        cooldown_ticks=cd,
                                        duracion_ticks=dur,
                                        horas_permitidas=horas,
                                        solo_calls=True,
                                    )
                                    
                                    if result['total'] >= 5:  # Mínimo 5 trades para considerar
                                        resultados.append(result)
    
    # Ordenar por edge (ventaja sobre breakeven)
    resultados.sort(key=lambda x: x['edge'], reverse=True)
    
    return resultados


def main():
    print("=" * 80)
    print("BACKTEST ESTRATEGIA SPP - R_100")
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
    
    # Convertir a listas
    precios = []
    epochs = []
    for tick in ticks:
        precios.append(float(tick.precio))
        epochs.append(int(tick.epoch))
    
    # Mostrar rango temporal
    if epochs:
        from_dt = datetime.utcfromtimestamp(epochs[0])
        to_dt = datetime.utcfromtimestamp(epochs[-1])
        print(f"Rango temporal: {from_dt} UTC -> {to_dt} UTC")
        
        # Distribución por hora
        horas_dist = {}
        for ep in epochs:
            h = datetime.utcfromtimestamp(ep).hour
            horas_dist[h] = horas_dist.get(h, 0) + 1
        
        print("\nDistribución de ticks por hora UTC:")
        for h in sorted(horas_dist.keys()):
            print(f"  {h:02d}:00 - {horas_dist[h]:5d} ticks")
    
    # Configuración actual (de .env)
    print("\n" + "=" * 80)
    print("CONFIGURACIÓN ACTUAL (del .env)")
    print("=" * 80)
    
    from django.conf import settings
    config_actual = {
        'ema_fast': settings.SPP_EMA_FAST,
        'ema_slow': settings.SPP_EMA_SLOW,
        'slope_n': settings.SPP_SLOPE_N,
        'min_gap': settings.SPP_MIN_EMA_GAP_R100,
        'slope_threshold': settings.SPP_SLOPE_THRESHOLD_R100,
        'cooldown': settings.SPP_COOLDOWN_TICKS,
        'duracion': 25,  # Default
    }
    for k, v in config_actual.items():
        print(f"  {k}: {v}")
    
    # Backtest con configuración actual
    print("\n" + "=" * 80)
    print("BACKTEST CON CONFIGURACIÓN ACTUAL")
    print("=" * 80)
    
    result_actual = backtest_spp(
        precios, epochs,
        ema_fast=config_actual['ema_fast'],
        ema_slow=config_actual['ema_slow'],
        slope_n=config_actual['slope_n'],
        min_gap=config_actual['min_gap'],
        slope_threshold=config_actual['slope_threshold'],
        cooldown_ticks=config_actual['cooldown'],
        duracion_ticks=config_actual['duracion'],
        horas_permitidas=[19, 22, 23],  # Basado en comentarios del .env
    )
    
    print(f"\nTRADES TOTALES: {result_actual['total']}")
    print(f"WINS: {result_actual['wins']}")
    print(f"LOSSES: {result_actual['losses']}")
    print(f"WINRATE: {result_actual['winrate']:.2f}%")
    print(f"BREAKEVEN: {result_actual['breakeven']:.2f}%")
    print(f"EDGE (ventaja): {result_actual['edge']:.2f}%")
    print(f"PROFIT: ${result_actual['profit']:.2f}")
    print(f"CAPITAL FINAL: ${result_actual['capital_final']:.2f}")
    
    # Análisis por hora
    if result_actual['trades']:
        print("\n--- ANÁLISIS POR HORA UTC ---")
        by_hour = analyze_by_hour(result_actual['trades'])
        for h in sorted(by_hour.keys()):
            data = by_hour[h]
            print(f"  {h:02d}:00 - WR: {data['winrate']:5.1f}% | Trades: {data['trades']:3d} | Profit: ${data['profit']:+.2f}")
    
    # Optimización
    print("\n" + "=" * 80)
    print("OPTIMIZACIÓN DE PARÁMETROS")
    print("=" * 80)
    
    resultados = optimize_params(precios, epochs)
    
    print(f"\nMEJORES 10 CONFIGURACIONES (por edge):")
    print("-" * 80)
    
    for i, r in enumerate(resultados[:10]):
        p = r['params']
        print(f"\n#{i+1} EDGE: {r['edge']:+.2f}% | WR: {r['winrate']:.1f}% | Trades: {r['total']}")
        print(f"   EMA({p['ema_fast']},{p['ema_slow']}) gap={p['min_gap']:.2f} slope={p['slope_threshold']:.2f}")
        print(f"   cooldown={p['cooldown_ticks']} dur={p['duracion_ticks']} horas={p['horas']}")
        print(f"   Profit: ${r['profit']:.2f} | Capital: ${r['capital_final']:.2f}")
    
    # Mejor configuración
    if resultados:
        mejor = resultados[0]
        print("\n" + "=" * 80)
        print("RECOMENDACIÓN: MEJOR CONFIGURACIÓN")
        print("=" * 80)
        p = mejor['params']
        print(f"""
WINRATE: {mejor['winrate']:.2f}% (breakeven es {mejor['breakeven']:.2f}%)
EDGE: {mejor['edge']:+.2f}% sobre breakeven
TRADES: {mejor['total']}
PROFIT: ${mejor['profit']:.2f}

PARÁMETROS RECOMENDADOS:
  ESTRATEGIA_TIPO=spp
  SPP_EMA_FAST={p['ema_fast']}
  SPP_EMA_SLOW={p['ema_slow']}
  SPP_SLOPE_N={p['slope_n']}
  SPP_MIN_EMA_GAP_R100={p['min_gap']}
  SPP_SLOPE_THRESHOLD_R100={p['slope_threshold']}
  SPP_COOLDOWN_TICKS={p['cooldown_ticks']}
  DERIV_DURACION_TICKS={p['duracion_ticks']}
  HORAS_PERMITIDAS_UTC={p['horas']}
""")
    
    return resultados


if __name__ == "__main__":
    resultados = main()
