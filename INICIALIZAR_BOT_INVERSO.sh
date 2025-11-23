#!/bin/bash
# Script para inicializar el bot inverso
# Este script sincroniza el balance desde Deriv, no establece un valor fijo

cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate

echo "Sincronizando balance del bot inverso desde Deriv..."
python manage.py shell << EOF
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.sincronizar_balance_desde_api()
config = gestor.configuracion
print(f'Balance sincronizado desde Deriv: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
EOF

echo "✅ Balance sincronizado correctamente desde Deriv"

