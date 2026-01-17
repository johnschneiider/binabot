#!/bin/bash
# Script de diagnóstico para bot que no entra después de operar

APP_DIR="/var/www/vitalmix.com.co/app"
VENV_ACTIVATE="$APP_DIR/.venv/bin/activate"
MANAGE_PY="$APP_DIR/manage.py"

echo "=== DIAGNÓSTICO: BOT NO ENTRA DESPUÉS DE OPERAR ==="
echo ""

# 1. Últimas operaciones realizadas
echo "1. ÚLTIMAS OPERACIONES REALIZADAS"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "30 minutes ago" --no-pager | grep -E "buy OK|Operación cerrada|cooldown" | tail -20
echo ""

# 2. Estado actual y decisión (últimos 50 ticks)
echo "2. ESTADO Y DECISIÓN RECIENTE"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "10 minutes ago" --no-pager | grep -E "\[EXTREMOS\]|\[TRADING\]|decision=" | tail -30
echo ""

# 3. SKIPs recientes (qué está bloqueando)
echo "3. SKIPS RECIENTES (¿QUÉ ESTÁ BLOQUEANDO?)"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "10 minutes ago" --no-pager | grep "SKIP" | tail -20
echo ""

# 4. Estado en BD vs estado en memoria (constructor_extremos)
echo "4. ESTADO EN BD"
echo "--------------------"
source "$VENV_ACTIVATE"
python "$MANAGE_PY" shell -c "
from gestion_riesgo.models import Cuenta
import time
c = Cuenta.objects.get(id=2)
now = int(time.time())
print(f'cuenta_id: {c.id}')
print(f'senal_decision: {c.senal_decision}')
print(f'bloqueado: {c.bloqueado}')
print(f'riesgo_motivo: {c.riesgo_motivo}')
if c.ciclo_pausa_hasta_epoch:
    resta = int(c.ciclo_pausa_hasta_epoch) - now
    print(f'ciclo_pausa_hasta_epoch: {c.ciclo_pausa_hasta_epoch} (restan {resta}s)')
"
echo ""

# 5. Verificar si hay señales pero se están rechazando
echo "5. SEÑALES RECIENTES (decision=VENTA/COMPRA pero no operando)"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "10 minutes ago" --no-pager | grep -E "decision=VENTA|decision=COMPRA" | grep -v "buy OK" | tail -20
echo ""

# 6. Verificar cooldown activo en logs
echo "6. COOLDOWN ACTIVO?"
echo "--------------------"
journalctl -u binabot-vitalmix.service --since "10 minutes ago" --no-pager | grep -E "COOLDOWN|cooldown|En cooldown" | tail -10
echo ""

# 7. Configuración de cooldown
echo "7. CONFIGURACIÓN COOLDOWN"
echo "--------------------"
python "$MANAGE_PY" shell -c "
from django.conf import settings
print(f'ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS: {getattr(settings, \"ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS\", None)}')
print(f'EXTREMOS_COOLDOWN_TICKS: {getattr(settings, \"EXTREMOS_COOLDOWN_TICKS\", None)}')
"
echo ""

echo "8. RESUMEN"
echo "--------------------"
echo "Si ves 'decision=VENTA' o 'decision=COMPRA' pero no hay 'buy OK':"
echo "  - Revisar SKIPs para ver qué está bloqueando"
echo ""
echo "Si ves 'COOLDOWN' o 'En cooldown':"
echo "  - El bot está en período de espera tras operación (normal)"
echo ""
echo "Si ves 'decision=NO_OPERAR' constantemente:"
echo "  - Las condiciones de entrada no se están cumpliendo"
echo ""
