"""
Monitoreo de 8 horas para el bot de trading
Revisa logs cada 60 segundos y genera reportes
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')

import django
django.setup()

from gestion_riesgo.models import Cuenta, OperacionDeriv
from django.db.models import Sum, Count


def get_current_hour_utc():
    """Obtiene la hora UTC actual."""
    return datetime.now(timezone.utc).hour


def parse_hora_local(epoch_str):
    """Convierte epoch a hora local Colombia (UTC-5)."""
    try:
        epoch = int(epoch_str)
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        hora_colombia = (dt.hour - 5) % 24
        return hora_colombia, dt
    except:
        return None, None


def analyze_log_file(log_path, minutes=5):
    """Analiza las últimas N minutos del log."""
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        # Solo últimas líneas
        recent = lines[-1000:] if len(lines) > 1000 else lines
        
        stats = {
            'total_lines': 0,
            'ticks_procesados': 0,
            'compras': 0,
            'ventas': 0,
            'no_operar': 0,
            'errores': 0,
            'ws_events': 0,
            'trading_events': 0,
            'balance_updates': 0,
            'razones_no_operar': {},
            'symbols': set(),
            'ultimo_tick': None,
            'ultimo_precio': None,
            'bloqueado': None,
            'capital': None,
            'ema_gap': None,
            'ultimo_error': None,
        }
        
        for line in recent:
            stats['total_lines'] += 1
            line_lower = line.lower()
            
            # Detectar símbolos
            if '[r_100]' in line_lower:
                stats['symbols'].add('R_100')
            if '[r_10]' in line_lower:
                stats['symbols'].add('R_10')
            if '[r_75v]' in line_lower or '[1hz75v]' in line_lower:
                stats['symbols'].add('1HZ75V')
            
            # Decisiones
            if 'dec=COMPRA' in line:
                stats['compras'] += 1
            if 'dec=VENTA' in line:
                stats['ventas'] += 1
            if 'dec=NO_OPERAR' in line:
                stats['no_operar'] += 1
            
            # Razones de no operar
            for reason in ['cooldown', 'mercado_choppy', 'gap_bajo', 'slope_negativo', 
                          'adx_debil', 'atr_bajo', 'atr_alto', 'rango_lateral',
                          'horario_bloqueado', 'fatiga', 'bloqueado_por', 'put_bloqueado']:
                if reason in line:
                    stats['razones_no_operar'][reason] = stats['razones_no_operar'].get(reason, 0) + 1
            
            # Errores
            if '[error]' in line_lower or '[fatal]' in line_lower or '[warn]' in line_lower:
                stats['errores'] += 1
                stats['ultimo_error'] = line.strip()[-200:]
            
            # WebSocket events
            if '[ws]' in line_lower:
                stats['ws_events'] += 1
            
            # Trading events
            if '[trading]' in line_lower:
                stats['trading_events'] += 1
            
            # Balance updates
            if '[balance]' in line_lower or 'balance=' in line:
                stats['balance_updates'] += 1
            
            # Extraer info del último tick
            if 't=' in line and 'p=' in line:
                parts = line.split()
                for p in parts:
                    if p.startswith('t='):
                        stats['ultimo_tick'] = p[2:]
                    if p.startswith('p='):
                        stats['ultimo_precio'] = p[2:]
                    if p.startswith('bloqueado='):
                        stats['bloqueado'] = p[10:]
                    if p.startswith('cap='):
                        stats['capital'] = p[4:]
                    if 'ema_gap:' in p:
                        stats['ema_gap'] = p.split('ema_gap:')[1] if 'ema_gap:' in p else None
            
            # Ticks procesados
            if 'n=' in line:
                try:
                    for p in line.split():
                        if p.startswith('n='):
                            n = int(p[2:])
                            if n > stats['ticks_procesados']:
                                stats['ticks_procesados'] = n
                except:
                    pass
        
        return stats
    except Exception as e:
        return {'error': str(e)}


def get_account_status():
    """Obtiene el estado actual de las cuentas."""
    status = {}
    for cuenta in Cuenta.objects.all():
        ops = OperacionDeriv.objects.filter(cuenta=cuenta)
        total = ops.count()
        wins = ops.filter(profit__gt=0).count()
        losses = ops.filter(profit__lte=0).count()
        total_profit = ops.aggregate(p=Sum('profit'))['p'] or 0
        
        # Verificar pausa de ciclo
        pausa_activa = False
        if cuenta.ciclo_pausa_hasta_epoch:
            ahora = int(datetime.now(timezone.utc).timestamp())
            if ahora < cuenta.ciclo_pausa_hasta_epoch:
                pausa_activa = True
        
        status[cuenta.simbolo] = {
            'balance': cuenta.balance_deriv,
            'capital': cuenta.capital_actual,
            'max_capital': cuenta.max_capital_historico,
            'bloqueado': cuenta.bloqueado,
            'riesgo_motivo': cuenta.riesgo_motivo,
            'pausa_ciclo': pausa_activa,
            'operaciones': total,
            'wins': wins,
            'losses': losses,
            'winrate': (wins / total * 100) if total > 0 else 0,
            'profit': total_profit,
        }
    return status


def print_status_report(cycle, start_time, stats, account_status):
    """Imprime el reporte de estado."""
    ahora = datetime.now(timezone.utc)
    elapsed = ahora - start_time
    remaining = max(0, 8 * 3600 - elapsed.total_seconds())
    remaining_h = remaining / 3600
    remaining_m = (remaining % 3600) / 60
    
    hora_utc = get_current_hour_utc()
    hora_colombia = (hora_utc - 5) % 24
    
    print("=" * 100)
    print(f"#{cycle:04d} | {ahora.strftime('%H:%M:%S')} UTC | {hora_colombia:02d}:00 Colombia")
    print(f"Elapsed: {elapsed.total_seconds()/3600:.2f}h | Remaining: {remaining_h:.1f}h ({remaining_m:.0f}m)")
    print("-" * 100)
    
    # Estado de horas (si estamos en hora boa)
    horas_boas_col = [9, 13, 15, 17]
    en_hora_boa = hora_colombia in horas_boas_col
    hora_boa_str = "HORA BUENA - OPERANDO" if en_hora_boa else "HORA MALA - BLOQUEADO"
    print(f"[HORA] {hora_colombia:02d}:00 Colombia ({hora_boa_str})")
    print()
    
    # Análisis de logs
    if 'error' in stats:
        print(f"[ERROR] No se pudo leer log: {stats['error']}")
    else:
        print(f"[LOGS] Total lines: {stats['total_lines']} | Ticks procesados: {stats['ticks_procesados']}")
        print(f"[LOGS] Símbolos activos: {', '.join(stats['symbols']) if stats['symbols'] else 'NINGUNO'}")
        print()
        
        print(f"[SENALES] COMPRA: {stats['compras']} | VENTA: {stats['ventas']} | NO_OPERAR: {stats['no_operar']}")
        
        if stats['ultimo_tick']:
            print(f"[ULTIMO TICK] Epoch: {stats['ultimo_tick']} | Precio: {stats['ultimo_precio']}")
            print(f"[ESTADO] Bloqueado: {stats['bloqueado']} | Capital: {stats['capital']} | EMA Gap: {stats['ema_gap']}")
        
        if stats['razones_no_operar']:
            print(f"[RAZONES NO OPERAR]")
            for reason, count in sorted(stats['razones_no_operar'].items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count}")
        
        if stats['errores'] > 0:
            print(f"[ALERTA] Errores detectados: {stats['errores']}")
            if stats['ultimo_error']:
                print(f"    Ultimo error: {stats['ultimo_error'][-150:]}")
        print()
    
    # Estado de cuentas
    print("[CUENTAS]")
    for symbol, acc in account_status.items():
        winrate_str = f"{acc['winrate']:.1f}%"
        profit_str = f"${acc['profit']:+.2f}"
        
        estado = "OK" if not acc['bloqueado'] else f"BLOQUEADO ({acc['riesgo_motivo']})"
        
        print(f"  {symbol}: Balance=${acc['balance']:.2f} | Capital=${acc['capital']:.2f} | "
              f"WR={winrate_str} | Profit={profit_str} | Ops={acc['operaciones']} | {estado}")
    
    print("=" * 100)
    print()


def main():
    print("\n" + "=" * 100)
    print("MONITOREO DE 8 HORAS - BOT TRADING")
    print("=" * 100)
    print(f"Inicio: {datetime.now(timezone.utc)} UTC")
    print("Revisiones cada 60 segundos")
    print("Horas boas (Colombia): 09:00, 13:00, 15:00, 17:00")
    print("=" * 100 + "\n")
    
    start_time = datetime.now(timezone.utc)
    cycle = 0
    max_cycles = 8 * 60  # 8 horas * 60 minutos
    
    log_path = Path("logs/runtime.log")
    if not log_path.exists():
        print(f"ADVERTENCIA: {log_path} no existe")
    
    # Primer reporte
    stats = analyze_log_file(log_path)
    account_status = get_account_status()
    print_status_report(cycle, start_time, stats, account_status)
    
    # Monitoreo cada 60 segundos
    while cycle < max_cycles:
        cycle += 1
        time.sleep(60)
        
        stats = analyze_log_file(log_path)
        account_status = get_account_status()
        print_status_report(cycle, start_time, stats, account_status)
        
        # Verificar si quedan ciclos
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        if elapsed >= 8 * 3600:
            print("\n[FIN] 8 horas completadas!")
            break
    
    # Reporte final
    print("\n" + "=" * 100)
    print("REPORTE FINAL - 8 HORAS DE MONITOREO")
    print("=" * 100)
    
    account_status = get_account_status()
    print("\n[RESUMEN CUENTAS]")
    for symbol, acc in account_status.items():
        print(f"  {symbol}:")
        print(f"    Balance: ${acc['balance']:.2f}")
        print(f"    Capital: ${acc['capital']:.2f}")
        print(f"    Max Capital: ${acc['max_capital']:.2f}")
        print(f"    Operaciones: {acc['operaciones']}")
        print(f"    Wins: {acc['wins']} | Losses: {acc['losses']}")
        print(f"    Winrate: {acc['winrate']:.1f}%")
        print(f"    Profit: ${acc['profit']:.2f}")
        print(f"    Bloqueado: {acc['bloqueado']} ({acc['riesgo_motivo']})")
        print()
    
    print(f"Fin monitoreo: {datetime.now(timezone.utc)} UTC")
    print("=" * 100)


if __name__ == "__main__":
    main()
