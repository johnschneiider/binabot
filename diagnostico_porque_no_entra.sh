#!/bin/bash
# Script de diagnóstico: ¿Por qué el bot no está haciendo entradas?

set -euo pipefail

APP_DIR="/var/www/vitalmix.com.co/app"
VENV_ACTIVATE="$APP_DIR/.venv/bin/activate"
MANAGE_PY="$APP_DIR/manage.py"
SERVICE_NAME="binabot-vitalmix.service"

echo "=========================================="
echo "  DIAGNÓSTICO: ¿POR QUÉ NO HAY ENTRADAS?"
echo "=========================================="
echo ""

# 1. ESTADO DEL BOT EN BD
echo "1. ESTADO DEL BOT (BASE DE DATOS)"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from gestion_riesgo.models import Cuenta
from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo
from datetime import datetime
import time

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now_epoch = int(time.time())
now_dt = timezone.now().astimezone(tz)

try:
    cuenta = Cuenta.objects.get(id=2)
    balance = cuenta.balance_deriv or cuenta.capital_actual
    
    print(f"cuenta_id: {cuenta.id}")
    print(f"simbolo: {cuenta.simbolo}")
    print(f"balance: {balance}")
    print(f"bloqueado: {cuenta.bloqueado}")
    print(f"riesgo_motivo: {cuenta.riesgo_motivo}")
    print(f"senal_decision: {cuenta.senal_decision}")
    print(f"senal_valor: {cuenta.senal_valor}")
    
    # Ciclo
    if cuenta.ciclo_balance_inicio:
        pnl_pct = ((balance / cuenta.ciclo_balance_inicio) - 1.0) * 100
        print(f"ciclo_balance_inicio: {cuenta.ciclo_balance_inicio}")
        print(f"PnL del ciclo: {pnl_pct:.2f}%")
    if cuenta.ciclo_inicio_epoch:
        dt_inicio = datetime.fromtimestamp(int(cuenta.ciclo_inicio_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
        print(f"ciclo_inicio_epoch: {cuenta.ciclo_inicio_epoch} ({dt_inicio.strftime('%Y-%m-%d %H:%M:%S')})")
    if cuenta.ciclo_pausa_hasta_epoch:
        resta = int(cuenta.ciclo_pausa_hasta_epoch) - now_epoch
        dt_pausa = datetime.fromtimestamp(int(cuenta.ciclo_pausa_hasta_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
        print(f"⚠️  ciclo_pausa_hasta_epoch: {cuenta.ciclo_pausa_hasta_epoch} ({dt_pausa.strftime('%Y-%m-%d %H:%M:%S')}) - Restan: {resta}s")
    else:
        print("ciclo_pausa_hasta_epoch: None (sin pausa)")
    
    # Ticks
    if cuenta.ultimo_tick_epoch:
        edad = now_epoch - int(cuenta.ultimo_tick_epoch)
        dt_tick = datetime.fromtimestamp(int(cuenta.ultimo_tick_epoch), tz=ZoneInfo("UTC")).astimezone(tz)
        print(f"ultimo_tick_epoch: {cuenta.ultimo_tick_epoch} ({dt_tick.strftime('%Y-%m-%d %H:%M:%S')})")
        print(f"edad_ultimo_tick: {edad}s ({edad/60:.1f}m)")
        if edad > 300:
            print("⚠️  Último tick hace más de 5 minutos - posible desconexión")
    else:
        print("⚠️  No hay último tick registrado")
    
    print(f"updated_at: {cuenta.updated_at.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
PY
echo ""

# 2. CONFIGURACIÓN CLAVE
echo "2. CONFIGURACIÓN CLAVE"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from django.conf import settings
from zoneinfo import ZoneInfo
from datetime import datetime

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
hora_actual = datetime.now(tz).hour

print("=== ESTRATEGIA ===")
print(f"ESTRATEGIA_TIPO: {getattr(settings, 'ESTRATEGIA_TIPO', None)}")
print(f"ESTRATEGIA_EXTREMOS_UMBRAL_RANGO: {getattr(settings, 'ESTRATEGIA_EXTREMOS_UMBRAL_RANGO', None)}")
print(f"ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS: {getattr(settings, 'ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS', None)}")

print("\n=== EXTREMOS ===")
print(f"EXTREMOS_VENTANA_TICKS: {getattr(settings, 'EXTREMOS_VENTANA_TICKS', None)}")
print(f"EXTREMOS_FRESCURA_TICKS: {getattr(settings, 'EXTREMOS_FRESCURA_TICKS', None)}")
print(f"EXTREMOS_MIN_REVERSION_FRAC: {getattr(settings, 'EXTREMOS_MIN_REVERSION_FRAC', None)}")
print(f"EXTREMOS_PROMEDIO_DELTA_FACTOR: {getattr(settings, 'EXTREMOS_PROMEDIO_DELTA_FACTOR', None)}")

print("\n=== DERIV ===")
print(f"DERIV_CONTRACT_TYPES_PERMITIDOS: {getattr(settings, 'DERIV_CONTRACT_TYPES_PERMITIDOS', None)}")
bloqueo_horas = getattr(settings, 'DERIV_BLOQUEO_HORAS_LOCAL', '')
print(f"DERIV_BLOQUEO_HORAS_LOCAL: {bloqueo_horas}")
if bloqueo_horas:
    horas_bloqueadas = []
    for rango in bloqueo_horas.split(','):
        rango = rango.strip()
        if '-' in rango:
            inicio, fin = map(int, rango.split('-'))
            horas_bloqueadas.extend(range(inicio, fin + 1))
        else:
            horas_bloqueadas.append(int(rango))
    print(f"Hora actual (local): {hora_actual:02d}:00")
    if hora_actual in horas_bloqueadas:
        print(f"⚠️  HORA ACTUAL ESTÁ BLOQUEADA ({hora_actual:02d}:00)")
    else:
        print(f"✅ Hora actual NO está bloqueada")
else:
    print("✅ Sin bloqueo horario")

print("\n=== STAKE ===")
from gestion_riesgo.models import Cuenta
try:
    cuenta = Cuenta.objects.get(id=2)
    balance = cuenta.balance_deriv or cuenta.capital_actual
    stake_calc = balance * 0.01
    stake_final = max(stake_calc, 0.35)
    print(f"Balance: {balance:.2f}")
    print(f"Stake calculado (1%): {stake_calc:.4f}")
    print(f"Stake final: {stake_final:.4f}")
except:
    pass
PY
echo ""

# 3. LOGS RECIENTES - DECISIONES Y RAZONES
echo "3. LOGS RECIENTES (ÚLTIMOS 10 MINUTOS)"
echo "----------------------------------------"
echo "=== Decisiones de la estrategia ==="
journalctl -u "$SERVICE_NAME" --since "10 minutes ago" --no-pager | grep -E "\[EXTREMOS\].*dec=" | tail -20
echo ""

echo "=== Razones de NO_OPERAR ==="
journalctl -u "$SERVICE_NAME" --since "10 minutes ago" --no-pager | grep -E "\[EXTREMOS\].*razon=" | tail -10
echo ""

echo "=== SKIPs (bloqueos) ==="
journalctl -u "$SERVICE_NAME" --since "10 minutes ago" --no-pager | grep "SKIP" | tail -15
echo ""

echo "=== Ticks recibidos ==="
journalctl -u "$SERVICE_NAME" --since "10 minutes ago" --no-pager | grep -E "\[UPDATE\] BD actualizada|tick=" | tail -10
echo ""

# 4. ÚLTIMAS OPERACIONES
echo "4. ÚLTIMAS OPERACIONES"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from gestion_riesgo.models import OperacionDeriv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now = timezone.now().astimezone(tz)
since = now - timedelta(hours=2)

ops = list(
    OperacionDeriv.objects
    .filter(creada_por_bot=True)
    .filter(created_at__gte=since)
    .order_by("-created_at")[:10]
)

print(f"Últimas 2 horas: {len(ops)} operaciones")
if ops:
    for o in ops:
        fecha = o.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        profit_str = f"profit={o.profit:.4f}" if o.profit is not None else "profit=None"
        print(f"  ID: {o.id} | {o.contract_type} | {o.estado} | {profit_str} | {fecha}")
else:
    print("⚠️  No hay operaciones en las últimas 2 horas")
PY
echo ""

# 5. RESUMEN Y DIAGNÓSTICO
echo "5. RESUMEN Y DIAGNÓSTICO"
echo "----------------------------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell <<'PY'
from gestion_riesgo.models import Cuenta
from django.conf import settings
from zoneinfo import ZoneInfo
from datetime import datetime
import time

tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
now_epoch = int(time.time())
hora_actual = datetime.now(tz).hour

try:
    cuenta = Cuenta.objects.get(id=2)
    
    problemas = []
    recomendaciones = []
    
    # 1. Verificar bloqueo
    if cuenta.bloqueado:
        problemas.append(f"❌ Bot BLOQUEADO: {cuenta.riesgo_motivo}")
        if cuenta.ciclo_pausa_hasta_epoch:
            resta = int(cuenta.ciclo_pausa_hasta_epoch) - now_epoch
            if resta > 0:
                problemas.append(f"   Pausa activa: {resta}s restantes")
            else:
                recomendaciones.append("Pausa vencida pero bot sigue bloqueado - reiniciar ciclo")
    
    # 2. Verificar ticks
    if cuenta.ultimo_tick_epoch:
        edad = now_epoch - int(cuenta.ultimo_tick_epoch)
        if edad > 300:
            problemas.append(f"❌ Último tick hace {edad}s ({edad/60:.1f}m) - posible desconexión")
            recomendaciones.append("Verificar conexión WebSocket a Deriv")
    else:
        problemas.append("❌ No hay ticks recibidos")
        recomendaciones.append("Verificar conexión WebSocket a Deriv")
    
    # 3. Verificar hora bloqueada
    bloqueo_horas = getattr(settings, 'DERIV_BLOQUEO_HORAS_LOCAL', '')
    if bloqueo_horas:
        horas_bloqueadas = []
        for rango in bloqueo_horas.split(','):
            rango = rango.strip()
            if '-' in rango:
                inicio, fin = map(int, rango.split('-'))
                horas_bloqueadas.extend(range(inicio, fin + 1))
            else:
                horas_bloqueadas.append(int(rango))
        if hora_actual in horas_bloqueadas:
            problemas.append(f"⚠️  Hora actual ({hora_actual:02d}:00) está BLOQUEADA")
    
    # 4. Verificar decisión
    if cuenta.senal_decision == "NO_OPERAR":
        problemas.append("ℹ️  Decisión: NO_OPERAR (revisar logs para razón)")
        recomendaciones.append("Revisar logs [EXTREMOS] para ver por qué no detecta entradas")
    
    # 5. Verificar cooldown
    cooldown_ticks = getattr(settings, 'ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS', 50)
    problemas.append(f"ℹ️  Cooldown configurado: {cooldown_ticks} ticks")
    
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
    
    if not problemas:
        print("✅ No se detectaron problemas obvios")
        print("   - Bot no bloqueado")
        print("   - Ticks recibidos recientemente")
        print("   - Revisar logs [EXTREMOS] para ver condiciones de entrada")
    
except Exception as e:
    print(f"Error: {e}")
PY
echo ""

echo "=========================================="
echo "  FIN DEL DIAGNÓSTICO"
echo "=========================================="
