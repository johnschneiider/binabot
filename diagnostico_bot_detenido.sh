#!/bin/bash
# Script de diagnóstico para bot detenido
# Verifica estado del servicio, logs, bloqueos, y configuración

cd /var/www/vitalmix.com.co/app || exit 1

echo "=== DIAGNÓSTICO: BOT DETENIDO ==="
echo ""

echo "1. ESTADO DEL SERVICIO"
echo "--------------------"
systemctl status binabot-vitalmix.service --no-pager -l | head -20
echo ""

echo "2. PROCESO ACTIVO"
echo "--------------------"
ps aux | grep "manage.py bot_con_panel" | grep -v grep || echo "❌ NO HAY PROCESO ACTIVO"
echo ""

echo "3. PUERTO ESCUCHANDO (8502)"
echo "--------------------"
ss -tlnp | grep 8502 || netstat -tlnp | grep 8502 || echo "❌ PUERTO 8502 NO ESTÁ ESCUCHANDO"
echo ""

echo "4. ÚLTIMOS 50 LOGS (ERRORES Y WARNINGS)"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "30 minutes ago" --no-pager | grep -E "ERROR|Exception|Traceback|WARN|SKIP|bloqueado|PAUSA" | tail -50 || echo "Sin errores recientes"
echo ""

echo "5. ÚLTIMOS TICKS RECIBIDOS"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "10 minutes ago" --no-pager | grep -E "tick=|UPDATE.*BD actualizada.*tick=" | tail -10 || echo "No hay ticks recientes"
echo ""

echo "6. ESTADO DE LA CUENTA (BASE DE DATOS)"
echo "--------------------"
source .venv/bin/activate
python manage.py shell << 'PYEOF'
from gestion_riesgo.models import Cuenta
import time

c = Cuenta.objects.order_by('-ultimo_tick_epoch', '-updated_at').first()
if c:
    print(f"cuenta_id: {c.id}")
    print(f"simbolo: {c.simbolo}")
    print(f"balance_deriv: {c.balance_deriv}")
    print(f"bloqueado: {c.bloqueado}")
    print(f"riesgo_motivo: {c.riesgo_motivo}")
    now = int(time.time())
    if c.ciclo_pausa_hasta_epoch:
        resta = int(c.ciclo_pausa_hasta_epoch) - now
        print(f"ciclo_pausa_hasta_epoch: {c.ciclo_pausa_hasta_epoch} (restan {resta}s = {resta//3600}h {resta%3600//60}m)")
    else:
        print(f"ciclo_pausa_hasta_epoch: None")
    print(f"ultimo_tick_epoch: {c.ultimo_tick_epoch}")
    if c.ultimo_tick_epoch:
        edad = now - int(c.ultimo_tick_epoch)
        print(f"edad_ultimo_tick: {edad}s ({edad//60}m)")
    print(f"senal_decision: {c.senal_decision}")
    print(f"senal_valor: {c.senal_valor}")
else:
    print("❌ NO HAY CUENTA EN LA BD")
PYEOF
echo ""

echo "7. CONFIGURACIÓN CLAVE"
echo "--------------------"
python manage.py shell << 'PYEOF'
from django.conf import settings
import os

print(f"DERIV_MODO_REAL: {settings.DERIV_MODO_REAL}")
print(f"DERIV_CONFIRMAR_REAL: {settings.DERIV_CONFIRMAR_REAL}")
print(f"CICLO_HABILITADO: {getattr(settings, 'CICLO_HABILITADO', None)}")
print(f"DRAWDOWN_GLOBAL_HABILITADO: {getattr(settings, 'DRAWDOWN_GLOBAL_HABILITADO', None)}")
print(f"ESTRATEGIA_TIPO: {getattr(settings, 'ESTRATEGIA_TIPO', None)}")
print(f"DERIV_CONTRACT_TYPES_PERMITIDOS: {getattr(settings, 'DERIV_CONTRACT_TYPES_PERMITIDOS', None)}")
print(f"DERIV_BLOQUEO_HORAS_LOCAL: {getattr(settings, 'DERIV_BLOQUEO_HORAS_LOCAL', None)}")
PYEOF
echo ""

echo "8. ÚLTIMAS OPERACIONES"
echo "--------------------"
python manage.py shell << 'PYEOF'
from gestion_riesgo.models import OperacionDeriv
from django.utils import timezone
from datetime import timedelta

ops = OperacionDeriv.objects.filter(creada_por_bot=True).order_by('-updated_at')[:5]
if ops:
    for op in ops:
        print(f"ID: {op.id} | Tipo: {op.contract_type} | Estado: {op.estado} | Profit: {op.profit} | Updated: {op.updated_at}")
else:
    print("No hay operaciones")
PYEOF
echo ""

echo "9. VERIFICAR CONEXIÓN WEBSOCKET"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "10 minutes ago" --no-pager | grep -E "\[WS\]|WebSocket|connected|disconnected|timeout" | tail -10 || echo "Sin logs de WebSocket recientes"
echo ""

echo "10. RECOMENDACIONES"
echo "--------------------"
echo "Si el bot está bloqueado:"
echo "  - Verificar 'bloqueado' y 'riesgo_motivo' en la BD"
echo "  - Verificar 'ciclo_pausa_hasta_epoch' si hay pausa activa"
echo ""
echo "Si no hay ticks:"
echo "  - Verificar conexión WebSocket a Deriv"
echo "  - Verificar DERIV_API_TOKEN y permisos"
echo ""
echo "Si hay errores:"
echo "  - Revisar logs completos: journalctl -u binabot-vitalmix.service -f"
