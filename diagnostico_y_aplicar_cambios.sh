#!/bin/bash
# Script para diagnosticar y aplicar cambios de optimización

cd /var/www/vitalmix.com.co/app || exit 1

echo "=== DIAGNÓSTICO DE CONFIGURACIÓN ACTUAL ==="
echo ""

# Verificar valores actuales
echo "1. DERIV_CONTRACT_TYPES_PERMITIDOS:"
grep "^DERIV_CONTRACT_TYPES_PERMITIDOS=" .env || echo "  ❌ NO ENCONTRADO"

echo ""
echo "2. DERIV_BLOQUEO_HORAS_LOCAL:"
grep "^DERIV_BLOQUEO_HORAS_LOCAL=" .env || echo "  ❌ NO ENCONTRADO"

echo ""
echo "3. EXTREMOS_MIN_REVERSION_FRAC:"
grep "^EXTREMOS_MIN_REVERSION_FRAC=" .env || echo "  ❌ NO ENCONTRADO"

echo ""
echo "4. EXTREMOS_PROMEDIO_DELTA_FACTOR:"
grep "^EXTREMOS_PROMEDIO_DELTA_FACTOR=" .env || echo "  ❌ NO ENCONTRADO"

echo ""
echo "5. ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS:"
grep "^ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=" .env || echo "  ❌ NO ENCONTRADO"

echo ""
echo "6. EXTREMOS_FRESCURA_TICKS:"
grep "^EXTREMOS_FRESCURA_TICKS=" .env || echo "  ❌ NO ENCONTRADO"

echo ""
echo "=== APLICANDO CAMBIOS ==="
echo ""

# Backup
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
echo "✓ Backup creado"

# Aplicar cambios
sed -i 's/^DERIV_BLOQUEO_HORAS_LOCAL=.*/DERIV_BLOQUEO_HORAS_LOCAL=1,2,6,8,10,11,12,13,14,15,22,23/' .env || echo "DERIV_BLOQUEO_HORAS_LOCAL=1,2,6,8,10,11,12,13,14,15,22,23" >> .env

sed -i 's/^DERIV_CONTRACT_TYPES_PERMITIDOS=.*/DERIV_CONTRACT_TYPES_PERMITIDOS=PUT/' .env || echo "DERIV_CONTRACT_TYPES_PERMITIDOS=PUT" >> .env

sed -i 's/^EXTREMOS_MIN_REVERSION_FRAC=.*/EXTREMOS_MIN_REVERSION_FRAC=0.10/' .env || echo "EXTREMOS_MIN_REVERSION_FRAC=0.10" >> .env

sed -i 's/^EXTREMOS_PROMEDIO_DELTA_FACTOR=.*/EXTREMOS_PROMEDIO_DELTA_FACTOR=1.5/' .env || echo "EXTREMOS_PROMEDIO_DELTA_FACTOR=1.5" >> .env

sed -i 's/^ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=.*/ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=50/' .env || echo "ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=50" >> .env

sed -i 's/^EXTREMOS_FRESCURA_TICKS=.*/EXTREMOS_FRESCURA_TICKS=3/' .env || echo "EXTREMOS_FRESCURA_TICKS=3" >> .env

echo ""
echo "=== VERIFICACIÓN DE CAMBIOS APLICADOS ==="
echo ""
grep -E "^DERIV_BLOQUEO_HORAS_LOCAL=|^DERIV_CONTRACT_TYPES_PERMITIDOS=|^EXTREMOS_MIN_REVERSION_FRAC=|^EXTREMOS_PROMEDIO_DELTA_FACTOR=|^ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=|^EXTREMOS_FRESCURA_TICKS=" .env

echo ""
echo "=== REINICIANDO SERVICIO ==="
systemctl restart binabot-vitalmix.service
sleep 3

echo ""
echo "=== ESTADO DEL SERVICIO ==="
systemctl status binabot-vitalmix.service --no-pager -l | head -20

echo ""
echo "=== VERIFICAR LOGS (últimas 20 líneas) ==="
journalctl -u binabot-vitalmix.service -n 20 --no-pager | grep -E "\[CFG\]|contract_types|horas_bloqueadas" || echo "No se encontraron líneas de configuración"

echo ""
echo "✓ Cambios aplicados. Monitorea con: journalctl -u binabot-vitalmix.service -f"
