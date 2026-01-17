#!/bin/bash
# Script de diagnóstico completo del bot
# Verifica: operaciones, ticks, BD, configuración, logs

set -euo pipefail

APP_DIR="/var/www/vitalmix.com.co/app"
VENV_ACTIVATE="$APP_DIR/.venv/bin/activate"
MANAGE_PY="$APP_DIR/manage.py"
SERVICE_NAME="binabot-vitalmix.service"

echo "=========================================="
echo "  DIAGNÓSTICO COMPLETO DEL BOT"
echo "=========================================="
echo ""

# 1. ESTADO DEL SERVICIO
echo "1. ESTADO DEL SERVICIO"
echo "----------------------------------------"
systemctl status "$SERVICE_NAME" --no-pager -l | head -15
echo ""

# 2. ÚLTIMAS OPERACIONES (24 HORAS)
echo "2. ÚLTIMAS OPERACIONES (ÚLTIMAS 24 HORAS)"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from gestion_riesgo.models import OperacionDeriv

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now = timezone.now().astimezone(tz)
since = now - timedelta(hours=24)
since_epoch = int(since.astimezone(ZoneInfo("UTC")).timestamp())

q = Q(opened_epoch__gte=since_epoch) | Q(opened_epoch__isnull=True, created_at__gte=since)
ops = list(
    OperacionDeriv.objects
    .filter(creada_por_bot=True)
    .filter(q)
    .order_by("-opened_epoch", "-created_at")[:50]
)

print(f"Desde: {since.isoformat()}")
print(f"Hasta: {now.isoformat()}")
print(f"Total operaciones: {len(ops)}\n")

if ops:
    cerradas = [o for o in ops if o.estado == "CERRADA" and o.profit is not None]
    abiertas = [o for o in ops if o.estado == "ABIERTA"]
    
    print(f"Cerradas: {len(cerradas)}")
    print(f"Abiertas: {len(abiertas)}\n")
    
    if cerradas:
        profits = [float(o.profit) for o in cerradas]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        print(f"Ganadoras: {len(wins)} ({len(wins)/len(cerradas)*100:.1f}%)")
        print(f"Perdedoras: {len(losses)} ({len(losses)/len(cerradas)*100:.1f}%)")
        print(f"Profit total: {sum(profits):.4f}")
        print(f"Profit promedio: {sum(profits)/len(profits):.4f}")
        if wins:
            print(f"Profit promedio ganadoras: {sum(wins)/len(wins):.4f}")
        if losses:
            print(f"Profit promedio perdedoras: {sum(losses)/len(losses):.4f}")
        print()
    
    print("Últimas 10 operaciones:")
    for o in ops[:10]:
        estado_str = o.estado
        profit_str = f"profit={o.profit:.4f}" if o.profit is not None else "profit=None"
        if o.opened_epoch:
            dt = datetime.fromtimestamp(int(o.opened_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
            fecha_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            fecha_str = o.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  ID: {o.id} | {o.contract_type} | {estado_str} | {profit_str} | {fecha_str}")
else:
    print("No hay operaciones en las últimas 24 horas")
PY
echo ""

# 3. ESTADO DE TICKS RECIBIDOS
echo "3. ESTADO DE TICKS RECIBIDOS"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone
from gestion_riesgo.models import Cuenta, TickDerivSnapshot
import time

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now_epoch = int(time.time())
now_dt = timezone.now().astimezone(tz)

# Estado de cuenta
try:
    cuenta = Cuenta.objects.get(id=2)
    print(f"Cuenta ID: {cuenta.id}")
    print(f"Símbolo: {cuenta.simbolo}")
    print(f"Balance: {cuenta.balance_deriv}")
    print(f"Último tick epoch: {cuenta.ultimo_tick_epoch}")
    print(f"Último precio: {cuenta.ultimo_precio}")
    
    if cuenta.ultimo_tick_epoch:
        edad_ticks = now_epoch - int(cuenta.ultimo_tick_epoch)
        edad_seg = edad_ticks
        edad_min = edad_seg / 60
        print(f"Edad último tick: {edad_seg}s ({edad_min:.1f}m)")
        
        if cuenta.ultimo_tick_epoch:
            dt_tick = datetime.fromtimestamp(int(cuenta.ultimo_tick_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
            print(f"Fecha último tick: {dt_tick.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("⚠️  No hay último tick registrado")
    
    print()
    
    # Ticks en BD (últimos 10)
    ticks = TickDerivSnapshot.objects.filter(cuenta=cuenta).order_by("-epoch")[:10]
    print(f"Ticks en BD (últimos 10): {ticks.count()}")
    if ticks.exists():
        for t in ticks:
            dt_t = datetime.fromtimestamp(int(t.epoch), tz=ZoneInfo("UTC")).astimezone(tz)
            print(f"  epoch={t.epoch} precio={t.precio:.5f} fecha={dt_t.strftime('%H:%M:%S')}")
    else:
        print("⚠️  No hay ticks en BD")
        
except Cuenta.DoesNotExist:
    print("⚠️  No se encontró cuenta con ID=2")
PY
echo ""

# 4. ESTADO DE LA BASE DE DATOS
echo "4. ESTADO DE LA BASE DE DATOS"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone
from gestion_riesgo.models import Cuenta
import time

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now_epoch = int(time.time())
now_dt = timezone.now().astimezone(tz)

try:
    cuenta = Cuenta.objects.get(id=2)
    print(f"cuenta_id: {cuenta.id}")
    print(f"simbolo: {cuenta.simbolo}")
    print(f"balance_deriv: {cuenta.balance_deriv}")
    print(f"bloqueado: {cuenta.bloqueado}")
    print(f"riesgo_motivo: {cuenta.riesgo_motivo}")
    print(f"senal_decision: {cuenta.senal_decision}")
    print(f"senal_valor: {cuenta.senal_valor}")
    
    # Ciclo
    if cuenta.ciclo_balance_inicio:
        print(f"ciclo_balance_inicio: {cuenta.ciclo_balance_inicio}")
    if cuenta.ciclo_inicio_epoch:
        dt_inicio = datetime.fromtimestamp(int(cuenta.ciclo_inicio_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
        print(f"ciclo_inicio_epoch: {cuenta.ciclo_inicio_epoch} ({dt_inicio.strftime('%Y-%m-%d %H:%M:%S')})")
    if cuenta.ciclo_pausa_hasta_epoch:
        resta = int(cuenta.ciclo_pausa_hasta_epoch) - now_epoch
        dt_pausa = datetime.fromtimestamp(int(cuenta.ciclo_pausa_hasta_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
        print(f"ciclo_pausa_hasta_epoch: {cuenta.ciclo_pausa_hasta_epoch} ({dt_pausa.strftime('%Y-%m-%d %H:%M:%S')}) - Restan: {resta}s")
    else:
        print("ciclo_pausa_hasta_epoch: None (sin pausa)")
    
    print(f"updated_at: {cuenta.updated_at.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')}")
    
except Cuenta.DoesNotExist:
    print("⚠️  No se encontró cuenta con ID=2")
PY
echo ""

# 5. CONFIGURACIÓN CLAVE
echo "5. CONFIGURACIÓN CLAVE"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from django.conf import settings

print("=== DERIV ===")
print(f"DERIV_MODO_REAL: {getattr(settings, 'DERIV_MODO_REAL', None)}")
print(f"DERIV_CONFIRMAR_REAL: {getattr(settings, 'DERIV_CONFIRMAR_REAL', None)}")
print(f"DERIV_SYMBOL: {getattr(settings, 'DERIV_SYMBOL', None)}")
print(f"DERIV_DURACION_TICKS: {getattr(settings, 'DERIV_DURACION_TICKS', None)}")
print(f"DERIV_CONTRACT_TYPES_PERMITIDOS: {getattr(settings, 'DERIV_CONTRACT_TYPES_PERMITIDOS', None)}")
print(f"DERIV_BLOQUEO_HORAS_LOCAL: {getattr(settings, 'DERIV_BLOQUEO_HORAS_LOCAL', None)}")

print("\n=== ESTRATEGIA ===")
print(f"ESTRATEGIA_TIPO: {getattr(settings, 'ESTRATEGIA_TIPO', None)}")
print(f"ESTRATEGIA_EXTREMOS_UMBRAL_RANGO: {getattr(settings, 'ESTRATEGIA_EXTREMOS_UMBRAL_RANGO', None)}")
print(f"ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS: {getattr(settings, 'ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS', None)}")

print("\n=== EXTREMOS ===")
print(f"EXTREMOS_VENTANA_TICKS: {getattr(settings, 'EXTREMOS_VENTANA_TICKS', None)}")
print(f"EXTREMOS_FRESCURA_TICKS: {getattr(settings, 'EXTREMOS_FRESCURA_TICKS', None)}")
print(f"EXTREMOS_MIN_REVERSION_FRAC: {getattr(settings, 'EXTREMOS_MIN_REVERSION_FRAC', None)}")
print(f"EXTREMOS_MIN_REVERSION_ABS: {getattr(settings, 'EXTREMOS_MIN_REVERSION_ABS', None)}")
print(f"EXTREMOS_PROMEDIO_DELTA_TICKS: {getattr(settings, 'EXTREMOS_PROMEDIO_DELTA_TICKS', None)}")
print(f"EXTREMOS_PROMEDIO_DELTA_FACTOR: {getattr(settings, 'EXTREMOS_PROMEDIO_DELTA_FACTOR', None)}")

print("\n=== CICLOS ===")
print(f"CICLO_HABILITADO: {getattr(settings, 'CICLO_HABILITADO', None)}")
print(f"CICLO_TAKE_PROFIT_PCT: {getattr(settings, 'CICLO_TAKE_PROFIT_PCT', None)}")
print(f"CICLO_STOPLOSS_PCT: {getattr(settings, 'CICLO_STOPLOSS_PCT', None)}")
print(f"CICLO_PAUSA_TP_SEG: {getattr(settings, 'CICLO_PAUSA_TP_SEG', None)}")
print(f"CICLO_PAUSA_SL_SEG: {getattr(settings, 'CICLO_PAUSA_SL_SEG', None)}")
PY
echo ""

# 6. LOGS RECIENTES (DECISIONES Y RAZONES)
echo "6. LOGS RECIENTES (ÚLTIMOS 5 MINUTOS)"
echo "----------------------------------------"
echo "=== Decisiones recientes ==="
journalctl -u "$SERVICE_NAME" --since "5 minutes ago" --no-pager | grep -E "dec=|decision=" | tail -20
echo ""
echo "=== Logs [EXTREMOS] con razones ==="
journalctl -u "$SERVICE_NAME" --since "5 minutes ago" --no-pager | grep "\[EXTREMOS\]" | tail -20
echo ""
echo "=== SKIPs (bloqueos) ==="
journalctl -u "$SERVICE_NAME" --since "5 minutes ago" --no-pager | grep "SKIP" | tail -10
echo ""

# 7. VERIFICAR CONEXIÓN WEBSOCKET
echo "7. VERIFICAR CONEXIÓN WEBSOCKET"
echo "----------------------------------------"
echo "=== Últimos ticks recibidos (logs) ==="
journalctl -u "$SERVICE_NAME" --since "5 minutes ago" --no-pager | grep -E "\[UPDATE\] BD actualizada|tick=" | tail -10
echo ""

# 8. RESUMEN Y RECOMENDACIONES
echo "8. RESUMEN Y RECOMENDACIONES"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone
from gestion_riesgo.models import Cuenta
import time

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now_epoch = int(time.time())

try:
    cuenta = Cuenta.objects.get(id=2)
    
    problemas = []
    recomendaciones = []
    
    # Verificar ticks
    if cuenta.ultimo_tick_epoch:
        edad = now_epoch - int(cuenta.ultimo_tick_epoch)
        if edad > 300:  # 5 minutos
            problemas.append(f"⚠️  Último tick hace {edad}s ({edad/60:.1f}m) - posible desconexión")
            recomendaciones.append("Verificar conexión WebSocket a Deriv")
    else:
        problemas.append("⚠️  No hay último tick registrado")
        recomendaciones.append("Verificar conexión WebSocket a Deriv")
    
    # Verificar bloqueo
    if cuenta.bloqueado:
        problemas.append(f"⚠️  Bot bloqueado: {cuenta.riesgo_motivo}")
        if cuenta.ciclo_pausa_hasta_epoch:
            resta = int(cuenta.ciclo_pausa_hasta_epoch) - now_epoch
            if resta > 0:
                problemas.append(f"   Pausa activa: {resta}s restantes")
            else:
                recomendaciones.append("Pausa vencida pero bot sigue bloqueado - verificar lógica de ciclo")
    
    # Verificar decisión
    if cuenta.senal_decision == "NO_OPERAR":
        problemas.append("ℹ️  Decisión: NO_OPERAR (revisar logs para razón)")
        recomendaciones.append("Revisar logs [EXTREMOS] para ver por qué no entra")
    
    if problemas:
        print("PROBLEMAS DETECTADOS:")
        for p in problemas:
            print(f"  {p}")
        print()
    
    if recomendaciones:
        print("RECOMENDACIONES:")
        for r in recomendaciones:
            print(f"  - {r}")
        print()
    
    if not problemas and not recomendaciones:
        print("✅ Estado general: OK")
        print("   - Ticks recibidos recientemente")
        print("   - Bot no bloqueado")
        print("   - Revisar logs para entender decisiones de entrada")
    
except Cuenta.DoesNotExist:
    print("⚠️  No se encontró cuenta con ID=2")
PY
echo ""

echo "=========================================="
echo "  FIN DEL DIAGNÓSTICO"
echo "=========================================="
