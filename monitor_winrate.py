#!/usr/bin/env python3
"""
Monitor de Winrate en Tiempo Real
Muestra estadísticas actuales y progreso hacia 80% WR
"""

import os
import django
import time
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quant_deriv_bot.settings')
django.setup()

from gestion_riesgo.models import OperacionBinance

def mostrar_estadisticas():
    print("\n" + "="*60)
    print("🎯 MONITOR WINRATE - BOT ULTRA CONSERVADOR")
    print("="*60)
    
    # Últimas 20 operaciones
    ops_20 = list(OperacionBinance.objects.order_by('-created_at')[:20])
    
    if not ops_20:
        print("❌ No hay operaciones registradas")
        return
    
    wins_20 = sum(1 for op in ops_20 if op.es_win)
    wr_20 = (wins_20 / len(ops_20)) * 100
    
    print(f"📊 ÚLTIMAS 20 OPERACIONES:")
    print(f"   Winrate: {wr_20:.1f}% ({wins_20}/{len(ops_20)})")
    
    # Target de 80%
    if wr_20 >= 80:
        print(f"   ✅ META ALCANZADA! ({wr_20:.1f}% >= 80%)")
    else:
        faltantes = max(0, 16 - wins_20)  # 16 wins de 20 = 80%
        print(f"   🎯 Faltan {faltantes} wins más para 80%")
    
    # Desglose detallado
    print(f"\n📈 ÚLTIMAS OPERACIONES:")
    for i, op in enumerate(ops_20[:10], 1):
        resultado = "✅" if op.es_win else "❌"
        tiempo = op.created_at.strftime("%H:%M")
        razon_corta = op.razon.split('_')[0][:15]
        print(f"   {i:2d}. {resultado} {op.simbolo} {op.direccion} @ {op.precio_entrada:.2f} | {tiempo} | {razon_corta}")
    
    if len(ops_20) > 10:
        wins_restantes = sum(1 for op in ops_20[10:] if op.es_win)
        total_restantes = len(ops_20[10:])
        print(f"   ... +{total_restantes} más ({wins_restantes} wins)")
    
    # Estadísticas por símbolo
    print(f"\n📋 POR SÍMBOLO (últimas 50 ops):")
    ops_50 = list(OperacionBinance.objects.order_by('-created_at')[:50])
    
    simbolos_stats = {}
    for op in ops_50:
        if op.simbolo not in simbolos_stats:
            simbolos_stats[op.simbolo] = {'wins': 0, 'total': 0}
        simbolos_stats[op.simbolo]['total'] += 1
        if op.es_win:
            simbolos_stats[op.simbolo]['wins'] += 1
    
    for simbolo, stats in sorted(simbolos_stats.items()):
        wr = (stats['wins'] / stats['total']) * 100 if stats['total'] > 0 else 0
        status = "🔥" if wr >= 70 else "⚠️" if wr >= 50 else "❄️"
        print(f"   {simbolo}: {status} {wr:.1f}% ({stats['wins']}/{stats['total']})")
    
    # Operaciones de hoy
    hoy = datetime.now().date()
    ops_hoy = OperacionBinance.objects.filter(created_at__date=hoy)
    if ops_hoy.exists():
        wins_hoy = sum(1 for op in ops_hoy if op.es_win)
        total_hoy = ops_hoy.count()
        wr_hoy = (wins_hoy / total_hoy) * 100
        print(f"\n🗓️  HOY ({hoy}):")
        print(f"   Operaciones: {total_hoy}")
        print(f"   Winrate: {wr_hoy:.1f}% ({wins_hoy}/{total_hoy})")
        
        profit_hoy = sum(float(op.profit) for op in ops_hoy)
        print(f"   P&L: ${profit_hoy:+.2f}")
    
    # Bot status
    print(f"\n🤖 ESTADO DEL BOT:")
    try:
        with open('/var/www/intradia.com.co/bot_80wr.log', 'r') as f:
            lines = f.readlines()[-5:]
            ultima_linea = lines[-1].strip() if lines else "Sin actividad"
            print(f"   Última actividad: {ultima_linea}")
    except:
        print("   ⚠️ No se puede leer el log")
    
    print("="*60)
    print(f"⏰ Actualizado: {datetime.now().strftime('%H:%M:%S')}")

def monitor_continuo():
    """Monitor continuo cada 30 segundos"""
    try:
        while True:
            os.system('clear')  # Limpiar pantalla
            mostrar_estadisticas()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n👋 Monitor detenido")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--continuo":
        monitor_continuo()
    else:
        mostrar_estadisticas()