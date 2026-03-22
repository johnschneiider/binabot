"""
REPORTE: Qué hubiera pasado si hubiéramos operado con las señales generadas.

Este script analiza las operaciones paper (Operacion) y calcula:
- Winrate de las operaciones paper
- Profit/Pérdida hypothetical
- Análisis por tipo de operación (CALL/PUT)
- Comparación con lo que el bot decidió en cada momento
"""

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import Operacion, Cuenta, TickDerivHistorico


def generar_reporte():
    print("=" * 80)
    print("REPORTE: QUE HUBIERA PASADO")
    print("=" * 80)
    
    # Obtener operaciones paper
    qs = Operacion.objects.filter(estado="CERRADA").order_by("-created_at")
    operaciones = list(qs[:500])
    
    if not operaciones:
        print("\nNo hay operaciones paper para analizar.")
        print("Las operaciones paper se generan cuando el bot opera en modo demo/paper.")
        return
    
    print(f"\nTotal operaciones paper: {len(operaciones)}")
    
    # Estadisticas generales
    total = len(operaciones)
    wins = sum(1 for op in operaciones if op.pnl_realizado and op.pnl_realizado > 0)
    losses = sum(1 for op in operaciones if op.pnl_realizado and op.pnl_realizado <= 0)
    profit_total = sum(op.pnl_realizado or 0 for op in operaciones)
    
    wr = (wins / total * 100) if total > 0 else 0
    breakeven = 100 / (1 + 0.85)  # ~54.05% con payout 0.85
    edge = wr - breakeven
    
    print(f"\n{'='*60}")
    print(f"RESUMEN GENERAL")
    print(f"{'='*60}")
    print(f"Total operaciones : {total}")
    print(f"Wins             : {wins} ({wins/total*100:.1f}%)")
    print(f"Losses           : {losses} ({losses/total*100:.1f}%)")
    print(f"Winrate          : {wr:.2f}%")
    print(f"Breakeven        : {breakeven:.2f}%")
    print(f"Edge             : {edge:+.2f}%")
    print(f"Profit Total     : ${profit_total:+.2f}")
    
    # Analisis por direccion
    print(f"\n{'='*60}")
    print(f"POR TIPO DE OPERACION")
    print(f"{'='*60}")
    
    for direccion in ["LARGO", "CORTO"]:
        ops_dir = [op for op in operaciones if op.direccion == direccion]
        if ops_dir:
            total_dir = len(ops_dir)
            wins_dir = sum(1 for op in ops_dir if op.pnl_realizado and op.pnl_realizado > 0)
            profit_dir = sum(op.pnl_realizado or 0 for op in ops_dir)
            wr_dir = (wins_dir / total_dir * 100) if total_dir > 0 else 0
            tipo_str = "CALL (LARGO)" if direccion == "LARGO" else "PUT (CORTO)"
            print(f"\n{tipo_str}:")
            print(f"  Total  : {total_dir}")
            print(f"  Wins   : {wins_dir} ({wr_dir:.1f}%)")
            print(f"  Profit : ${profit_dir:+.2f}")
    
    # Analisis por simbolo
    print(f"\n{'='*60}")
    print(f"POR ACTIVO")
    print(f"{'='*60}")
    
    simbolos = set(op.simbolo for op in operaciones)
    for simbolo in simbolos:
        ops_sym = [op for op in operaciones if op.simbolo == simbolo]
        if ops_sym:
            total_sym = len(ops_sym)
            wins_sym = sum(1 for op in ops_sym if op.pnl_realizado and op.pnl_realizado > 0)
            profit_sym = sum(op.pnl_realizado or 0 for op in ops_sym)
            wr_sym = (wins_sym / total_sym * 100) if total_sym > 0 else 0
            print(f"\n{simbolo}:")
            print(f"  Total  : {total_sym}")
            print(f"  Wins   : {wins_sym} ({wr_sym:.1f}%)")
            print(f"  Profit : ${profit_sym:+.2f}")
    
    # Analisis por hora (si hay epoch)
    print(f"\n{'='*60}")
    print(f"POR HORA (Colombia)")
    print(f"{'='*60}")
    
    hora_stats = {}
    for op in operaciones:
        if op.opened_epoch:
            try:
                dt = datetime.fromtimestamp(int(op.opened_epoch), tz=timezone.utc)
                tz_col = ZoneInfo('America/Bogota')
                dt_col = dt.astimezone(tz_col)
                hora = dt_col.hour
                
                if hora not in hora_stats:
                    hora_stats[hora] = {"total": 0, "wins": 0, "profit": 0}
                
                hora_stats[hora]["total"] += 1
                if op.pnl_realizado and op.pnl_realizado > 0:
                    hora_stats[hora]["wins"] += 1
                hora_stats[hora]["profit"] += op.pnl_realizado or 0
            except:
                pass
    
    if hora_stats:
        for hora in sorted(hora_stats.keys()):
            stats = hora_stats[hora]
            wr_hora = (stats["wins"] / stats["total"] * 100) if stats["total"] > 0 else 0
            print(f"  {hora:02d}:00 - {stats['total']:3d} ops | WR: {wr_hora:5.1f}% | Profit: ${stats['profit']:+.2f}")
    
    # Conclusiones
    print(f"\n{'='*60}")
    print(f"CONCLUSIONES")
    print(f"{'='*60}")
    
    if wr > breakeven:
        print(f"[OK] WINRATE {wr:.1f}% SUPERIOR AL BREAKEVEN {breakeven:.1f}%")
        print(f"     Edge positivo: {edge:+.2f}%")
        print(f"     El bot paper trading ES RENTABLE.")
    else:
        print(f"[MAL] WINRATE {wr:.1f}% INFERIOR AL BREAKEVEN {breakeven:.1f}%")
        print(f"      Edge negativo: {edge:.2f}%")
        print(f"      Necesitas mejorar la estrategia para superar breakeven.")
    
    if profit_total > 0:
        print(f"\n[OK] PROFIT TOTAL POSITIVO: ${profit_total:+.2f}")
    else:
        print(f"\n[MAL] PROFIT TOTAL NEGATIVO: ${profit_total:+.2f}")
    
    # Recomendaciones
    print(f"\n{'='*60}")
    print(f"RECOMENDACIONES")
    print(f"{'='*60}")
    
    # Mejor y peor hora
    if hora_stats:
        mejores = sorted(hora_stats.items(), key=lambda x: x[1]["wins"]/x[1]["total"] if x[1]["total"] > 0 else 0, reverse=True)[:3]
        peores = sorted(hora_stats.items(), key=lambda x: x[1]["wins"]/x[1]["total"] if x[1]["total"] > 0 else 1.0)[:3]
        
        print("\nMejores horas para operar (Colombia):")
        for hora, stats in mejores:
            wr_h = (stats["wins"] / stats["total"] * 100) if stats["total"] > 0 else 0
            print(f"  {hora:02d}:00 - {stats['total']} ops, WR: {wr_h:.1f}%")
        
        print("\nPeores horas (evitar):")
        for hora, stats in peores:
            wr_h = (stats["wins"] / stats["total"] * 100) if stats["total"] > 0 else 0
            print(f"  {hora:02d}:00 - {stats['total']} ops, WR: {wr_h:.1f}%")
    
    print(f"\n{'='*80}")
    print("FIN DEL REPORTE")
    print(f"{'='*80}")
    
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "winrate": wr,
        "profit": profit_total,
        "edge": edge,
    }


if __name__ == "__main__":
    generar_reporte()
