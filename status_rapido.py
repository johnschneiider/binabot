"""
MONITOREO RAPIDO - Status instantaneo del bot
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import Cuenta, OperacionDeriv
from django.db.models import Sum


def main():
    ahora = datetime.now(timezone.utc)
    hora_utc = ahora.hour
    hora_colombia = (hora_utc - 5) % 24
    
    horas_boas_col = [9, 13, 15, 17]
    horas_boas_utc = [14, 18, 20, 22]
    
    en_hora_boa = hora_colombia in horas_boas_col
    hora_boa_equiv_utc = (hora_colombia + 5) % 24
    
    print("=" * 80)
    print(f"MONITOREO - {ahora.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 80)
    
    # Hora actual
    print(f"\n[HORA ACTUAL]")
    print(f"  UTC: {hora_utc:02d}:00")
    print(f"  Colombia (UTC-5): {hora_colombia:02d}:00")
    print(f"  Hora boa: {'SI' if en_hora_boa else 'NO'} (debe ser 09, 13, 15, 17 Colombia)")
    if hora_boa_equiv_utc in horas_boas_utc:
        print(f"  Equivalente UTC buena: {hora_boa_equiv_utc:02d}:00")
    print()
    
    # Log reciente
    log_path = Path("logs/runtime.log")
    if log_path.exists():
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        # Últimas 20 líneas
        recent = lines[-20:]
        
        print(f"[LOGS] Ultimas 20 entradas:")
        for line in recent:
            print(f"  {line.strip()}")
        
        # Análisis de los últimos 100 ticks
        ticks_lines = [l for l in lines[-500:] if 't=' in l and 'dec=' in l]
        
        stats = {'COMPRA': 0, 'VENTA': 0, 'NO_OPERAR': 0}
        razones = {}
        
        for line in ticks_lines:
            if 'dec=COMPRA' in line:
                stats['COMPRA'] += 1
            elif 'dec=VENTA' in line:
                stats['VENTA'] += 1
            elif 'dec=NO_OPERAR' in line:
                stats['NO_OPERAR'] += 1
            
            for r in ['cooldown', 'mercado_choppy', 'gap_bajo', 'slope_negativo', 
                     'adx_debil', 'atr', 'rango_lateral', 'horario_bloqueado']:
                if r in line.lower():
                    razones[r] = razones.get(r, 0) + 1
        
        print(f"\n[ESTADISTICAS ULTIMOS ~500 TICKS]")
        print(f"  COMPRA: {stats['COMPRA']} | VENTA: {stats['VENTA']} | NO_OPERAR: {stats['NO_OPERAR']}")
        
        if razones:
            print(f"  Razones NO_OPERAR:")
            for r, c in sorted(razones.items(), key=lambda x: -x[1]):
                print(f"    {r}: {c}")
    else:
        print("[ERROR] logs/runtime.log no encontrado")
    
    # Estado de cuentas
    print(f"\n[ESTADO CUENTAS]")
    for cuenta in Cuenta.objects.all():
        ops = OperacionDeriv.objects.filter(cuenta=cuenta)
        total = ops.count()
        wins = ops.filter(profit__gt=0).count()
        losses = ops.filter(profit__lte=0).count()
        total_profit = ops.aggregate(p=Sum('profit'))['p'] or 0
        winrate = (wins / total * 100) if total > 0 else 0
        
        # Verificar pausa
        pausa = ""
        if cuenta.ciclo_pausa_hasta_epoch:
            ahora_epoch = int(datetime.now(timezone.utc).timestamp())
            if ahora_epoch < cuenta.ciclo_pausa_hasta_epoch:
                restante = cuenta.ciclo_pausa_hasta_epoch - ahora_epoch
                pausa = f"PAUSA ({restante//60}m {restante%60}s)"
        
        estado = "OK" if not cuenta.bloqueado else f"BLOQUEADO {pausa or cuenta.riesgo_motivo}"
        
        print(f"\n  [{cuenta.simbolo}]")
        print(f"    Balance: ${cuenta.balance_deriv:.2f}" if cuenta.balance_deriv else "    Balance: N/A")
        print(f"    Capital: ${cuenta.capital_actual:.2f}")
        print(f"    Ops: {total} | Wins: {wins} | Losses: {losses}")
        print(f"    WR: {winrate:.1f}% | Profit: ${total_profit:+.2f}")
        print(f"    Estado: {estado}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
