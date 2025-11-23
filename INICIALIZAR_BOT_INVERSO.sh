#!/bin/bash
# Script para inicializar el bot inverso

cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate

echo "Inicializando balance del bot inverso..."
python manage.py shell << EOF
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
config.balance_actual = 100.00
config.save()
print(f'Balance inicial configurado: \${config.balance_actual}')
EOF

echo "✅ Balance inicializado correctamente"

