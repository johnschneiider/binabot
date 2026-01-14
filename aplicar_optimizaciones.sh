#!/bin/bash
# Script para aplicar optimizaciones inmediatas al bot
# Basado en análisis de 48 horas

ENV_FILE="/var/www/vitalmix.com.co/app/.env"

echo "=== APLICANDO OPTIMIZACIONES AL BOT ==="
echo ""

# Verificar que el archivo existe
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: No se encontró $ENV_FILE"
    exit 1
fi

# Backup del .env
cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
echo "✓ Backup creado: ${ENV_FILE}.backup.*"

# 1. BLOQUEAR HORAS PROBLEMÁTICAS (100% perdedoras consistentemente)
echo "1. Bloqueando horas problemáticas (1,2,6,8,10,11,12,13,14,15,22,23)..."
if grep -q "^DERIV_BLOQUEO_HORAS_LOCAL=" "$ENV_FILE"; then
    sed -i 's/^DERIV_BLOQUEO_HORAS_LOCAL=.*/DERIV_BLOQUEO_HORAS_LOCAL=1,2,6,8,10,11,12,13,14,15,22,23/' "$ENV_FILE"
else
    echo "DERIV_BLOQUEO_HORAS_LOCAL=1,2,6,8,10,11,12,13,14,15,22,23" >> "$ENV_FILE"
fi

# 2. OPERAR SOLO PUT (mejor winrate: 52.3% vs CALL 47.8%)
echo "2. Configurando para operar solo PUT..."
if grep -q "^DERIV_CONTRACT_TYPES_PERMITIDOS=" "$ENV_FILE"; then
    sed -i 's/^DERIV_CONTRACT_TYPES_PERMITIDOS=.*/DERIV_CONTRACT_TYPES_PERMITIDOS=PUT/' "$ENV_FILE"
else
    echo "DERIV_CONTRACT_TYPES_PERMITIDOS=PUT" >> "$ENV_FILE"
fi

# 3. AUMENTAR SELECTIVIDAD (aumentar min_reversion para evitar entradas en ruido)
echo "3. Aumentando selectividad (min_reversion 0.05 -> 0.10)..."
if grep -q "^EXTREMOS_MIN_REVERSION_FRAC=" "$ENV_FILE"; then
    sed -i 's/^EXTREMOS_MIN_REVERSION_FRAC=.*/EXTREMOS_MIN_REVERSION_FRAC=0.10/' "$ENV_FILE"
else
    echo "EXTREMOS_MIN_REVERSION_FRAC=0.10" >> "$ENV_FILE"
fi

echo "4. Aumentando delta factor (1.0 -> 1.5)..."
if grep -q "^EXTREMOS_PROMEDIO_DELTA_FACTOR=" "$ENV_FILE"; then
    sed -i 's/^EXTREMOS_PROMEDIO_DELTA_FACTOR=.*/EXTREMOS_PROMEDIO_DELTA_FACTOR=1.5/' "$ENV_FILE"
else
    echo "EXTREMOS_PROMEDIO_DELTA_FACTOR=1.5" >> "$ENV_FILE"
fi

# 4. AUMENTAR COOLDOWN (reducir frecuencia de operaciones)
echo "5. Aumentando cooldown (25 -> 50 ticks)..."
if grep -q "^ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=" "$ENV_FILE"; then
    sed -i 's/^ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=.*/ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=50/' "$ENV_FILE"
else
    echo "ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=50" >> "$ENV_FILE"
fi

# 5. AUMENTAR FRESCURA (solo extremos muy recientes)
echo "6. Aumentando frescura de extremos (5 -> 3 ticks)..."
if grep -q "^EXTREMOS_FRESCURA_TICKS=" "$ENV_FILE"; then
    sed -i 's/^EXTREMOS_FRESCURA_TICKS=.*/EXTREMOS_FRESCURA_TICKS=3/' "$ENV_FILE"
else
    echo "EXTREMOS_FRESCURA_TICKS=3" >> "$ENV_FILE"
fi

echo ""
echo "=== VERIFICACIÓN DE CAMBIOS ==="
echo ""
grep -E "^DERIV_BLOQUEO_HORAS_LOCAL=|^DERIV_CONTRACT_TYPES_PERMITIDOS=|^EXTREMOS_MIN_REVERSION_FRAC=|^EXTREMOS_PROMEDIO_DELTA_FACTOR=|^ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS=|^EXTREMOS_FRESCURA_TICKS=" "$ENV_FILE" || echo "Algunas variables no encontradas (se agregaron al final)"

echo ""
echo "=== CAMBIOS APLICADOS ==="
echo "✓ Horas bloqueadas: 1,2,6,8,10,11,12,13,14,15,22,23"
echo "✓ Solo PUT (winrate 52.3% vs CALL 47.8%)"
echo "✓ Min reversión: 0.10 (antes 0.05) - más selectivo"
echo "✓ Delta factor: 1.5 (antes 1.0) - exige reversiones mayores"
echo "✓ Cooldown: 50 ticks (antes 25) - menos operaciones"
echo "✓ Frescura: 3 ticks (antes 5) - solo extremos muy recientes"
echo ""
echo "=== PRÓXIMOS PASOS ==="
echo "1. Reinicia el servicio: systemctl restart binabot-vitalmix.service"
echo "2. Monitorea los logs: journalctl -u binabot-vitalmix.service -f"
echo "3. Revisa resultados en 24h: python manage.py analizar_operaciones --horas 24"
echo ""
