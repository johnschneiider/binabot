"""
Backtest detallado por hora - Identificar las mejores ventanas horarias
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


def backtest_por_hora(precios: list, epochs: list) -> dict:
    """Analiza performance por hora UTC con EMA(5,13) baseline."""
    
    resultados_por_hora = {}
    
    # Probar cada hora individualmente
    for hora_tested in range(24):
        config = {
            'ema_fast': 5,
            'ema_slow': 13,
            'slope_n': 5,
            'min_gap': 0.30,
            'slope_threshold': 0.30,
            'cooldown_ticks': 15,
            'duracion_ticks': 20,
            'horas': [hora_tested],
            'solo_calls': False,  # Habilitar PUT para mayor样本
            'payout': 0.85,
            'min_stake': 1.0,
        }
        
        result = backtest_spp(precios, epochs, config)
        
        if result['total'] > 0:
            resultados_por_hora[hora_tested] = result
    
    return resultados_por_hora


def backtest_spp(precios: list, epochs: list, config: dict) -> dict:
    """Backtest con configuración."""
    ema_fast = config['ema_fast']
    ema_slow = config['ema_slow']
    slope_n = config['slope_n']
    min_gap = config['min_gap']
    slope_threshold = config['slope_threshold']
    cooldown_ticks = config['cooldown_ticks']
    duracion_ticks = config['duracion_ticks']
    horas_permitidas = config.get('horas', list(range(24)))
    solo_calls = config.get('solo_calls', True)
    payout = config.get('payout', 0.85)
    min_stake = config.get('min_stake', 1.0)
    
    ema_fast_val = None
    ema_slow_val = None
    ema_fast_hist = deque(maxlen=64)
    
    capital = 100.0
    trades = []
    wins = 0
    losses = 0
    cooldown_restante = 0
    
    for i in range(len(precios)):
        precio = float(precios[i])
        epoch = epochs[i]
        
        if ema_fast_val is None:
            ema_fast_val = precio
            ema_slow_val = precio
        else:
            ema_fast_val = ema_incremental(ema_fast_val, precio, ema_fast)
            ema_slow_val = ema_incremental(ema_slow_val, precio, ema_slow)
        
        ema_fast_hist.append(ema_fast_val)
        
        if cooldown_restante > 0:
            cooldown_restante -= 1
            continue
        
        try:
            hora_utc = datetime.fromtimestamp(int(epoch), tz=timezone.utc).hour
            if hora_utc not in horas_permitidas:
                continue
        except:
            continue
        
        if len(ema_fast_hist) < ema_slow + slope_n:
            continue
        
        ema_gap = abs(ema_fast_val - ema_slow_val)
        slope_val = _slope(ema_fast_hist, slope_n)
        
        if ema_fast_val > ema_slow_val:
            bias = "CALL"
        elif ema_fast_val < ema_slow_val:
            bias = "PUT"
        else:
            continue
        
        if bias == "CALL" and ema_gap >= min_gap:
            if slope_val is not None and slope_val > slope_threshold:
                if i + duracion_ticks < len(precios):
                    precio_salida = precios[i + duracion_ticks]
                    ganancia = min_stake * payout if precio_salida > precio else -min_stake
                else:
                    ganancia = 0
                
                capital += ganancia
                trades.append({'hora': hora_utc, 'ganancia': ganancia, 'direccion': 'CALL'})
                
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
                trades.append({'hora': hora_utc, 'ganancia': ganancia, 'direccion': 'PUT'})
                
                if ganancia > 0:
                    wins += 1
                else:
                    losses += 1
                
                cooldown_restante = cooldown_ticks
    
    total = len(trades)
    winrate = (wins / total * 100) if total > 0 else 0
    breakeven = 100 / (1 + payout)
    
    return {
        'trades': trades,
        'wins': wins,
        'losses': losses,
        'total': total,
        'winrate': winrate,
        'profit': capital - 100,
        'capital_final': capital,
        'breakeven': breakeven,
        'edge': winrate - breakeven,
    }


def probar_combinaciones_horas(precios: list, epochs: list) -> list:
    """Probar diferentes combinaciones de horas."""
    
    # Probar combinaciones prometedoras
    combinaciones = [
        ([22], "Solo 22h"),
        ([21, 22], "21h-22h"),
        ([20, 22], "20h-22h"),
        ([19, 22], "19h-22h"),
        ([19, 20, 22], "19h-20h-22h"),
        ([18, 19, 22], "18h-19h-22h"),
        ([17, 18, 19], "17h-19h"),
        ([22, 23], "22h-23h"),
        ([14, 15, 16], "14h-16h (trade morning)"),
        ([12, 13, 14], "12h-14h (trade morning)"),
        ([0, 1, 2], "00h-02h (late night)"),
        ([0, 2], "00h-02h (skip 01)"),
    ]
    
    resultados = []
    
    for horas, nombre in combinaciones:
        config = {
            'ema_fast': 5,
            'ema_slow': 13,
            'slope_n': 5,
            'min_gap': 0.30,
            'slope_threshold': 0.30,
            'cooldown_ticks': 15,
            'duracion_ticks': 20,
            'horas': horas,
            'solo_calls': False,
        }
        
        result = backtest_spp(precios, epochs, config)
        result['nombre'] = nombre
        result['horas'] = horas
        resultados.append(result)
    
    return resultados


def probar_gaps_diferentes(precios: list, epochs: list) -> list:
    """Probar diferentes valores de gap mínimo."""
    
    horas_base = [19, 22]
    
    gaps = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    resultados = []
    
    for gap in gaps:
        config = {
            'ema_fast': 5,
            'ema_slow': 13,
            'slope_n': 5,
            'min_gap': gap,
            'slope_threshold': gap * 0.9,  # Slope threshold proporcional
            'cooldown_ticks': 15,
            'duracion_ticks': 20,
            'horas': horas_base,
            'solo_calls': False,
        }
        
        result = backtest_spp(precios, epochs, config)
        result['gap'] = gap
        resultados.append(result)
    
    return resultados


def main():
    print("=" * 80)
    print("ANALISIS DETALLADO POR HORA")
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
    
    # Análisis por hora
    print("\n" + "=" * 80)
    print("ANALISIS POR HORA INDIVIDUAL")
    print("=" * 80)
    
    resultados_hora = backtest_por_hora(precios, epochs)
    
    horas_buenas = []
    horas_malas = []
    
    for hora in sorted(resultados_hora.keys()):
        r = resultados_hora[hora]
        edge = r['edge']
        mas_menos = "+" if edge >= 0 else ""
        print(f"  {hora:02d}h: WR={r['winrate']:5.1f}% | Trades={r['total']:3d} | Edge={mas_menos}{edge:5.1f}% | Profit=${r['profit']:+.2f}")
        
        if r['total'] >= 5:  # Mínimo 5 trades para considerar válido
            if edge > 5:
                horas_buenas.append(hora)
            elif edge < -10:
                horas_malas.append(hora)
    
    print(f"\nHoras BUENAS (edge > 5%): {horas_buenas}")
    print(f"Horas MALAS (edge < -10%): {horas_malas}")
    
    # Probar combinaciones
    print("\n" + "=" * 80)
    print("COMBINACIONES DE HORAS")
    print("=" * 80)
    
    combinaciones = probar_combinaciones_horas(precios, epochs)
    combinaciones.sort(key=lambda x: x['edge'], reverse=True)
    
    for r in combinaciones:
        edge = r['edge']
        mas_menos = "+" if edge >= 0 else ""
        print(f"  {r['nombre']:25s}: WR={r['winrate']:5.1f}% | Trades={r['total']:3d} | Edge={mas_menos}{edge:5.1f}% | Profit=${r['profit']:+.2f}")
    
    # Probar gaps
    print("\n" + "=" * 80)
    print("SENSIBILIDAD AL GAP MINIMO")
    print("=" * 80)
    
    gaps = probar_gaps_diferentes(precios, epochs)
    for r in gaps:
        edge = r['edge']
        mas_menos = "+" if edge >= 0 else ""
        print(f"  Gap={r['gap']:.2f}: WR={r['winrate']:5.1f}% | Trades={r['total']:3d} | Edge={mas_menos}{edge:5.1f}% | Profit=${r['profit']:+.2f}")
    
    # Mejor combinación
    mejor = combinaciones[0]
    
    print("\n" + "=" * 80)
    print("MEJOR COMBINACION ENCONTRADA")
    print("=" * 80)
    
    print(f"""
Nombre: {mejor['nombre']}
Winrate: {mejor['winrate']:.1f}% (breakeven: {mejor['breakeven']:.1f}%)
Edge: {mejor['edge']:+.1f}%
Trades: {mejor['total']}
Profit: ${mejor['profit']:.2f}

Configuracion recomendada:
  HORAS_PERMITIDAS={mejor['horas']}
  SPP_EMA_FAST=5
  SPP_EMA_SLOW=13
  SPP_SLOPE_N=5
  SPP_MIN_EMA_GAP_R100=0.30
  SPP_SLOPE_THRESHOLD_R100=0.30
  SPP_COOLDOWN_TICKS=15
  DERIV_DURACION_TICKS=20
  DERIV_CONTRACT_TYPES_PERMITIDOS=CALL,PUT
""")
    
    return mejor


if __name__ == "__main__":
    main()
