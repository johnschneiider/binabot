# Comando para Reanudar el Bot Principal

## Comando Rápido

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
config.reanudar()
print(f'Bot principal reanudado. Estado: {config.estado}')
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
"
```

## Verificar Estado Antes de Reanudar

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
print(f'Estado actual: {config.estado}')
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
print(f'Pausado desde: {config.pausado_desde}')
print(f'Pausa finaliza: {config.pausa_finaliza}')
if config.balance_actual > config.stop_loss_actual:
    print('✅ Balance está por encima del stop loss. Se puede reanudar.')
else:
    print('⚠️ Balance está por debajo del stop loss. No se debe reanudar.')
"
```

## Reanudar y Verificar

```bash
python manage.py shell << EOF
from core.models import ConfiguracionBot
from core.services import GestorBotCore

config = ConfiguracionBot.obtener()
print(f'Estado ANTES: {config.estado}')
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')

# Reanudar
config.reanudar()

# Verificar
config.refresh_from_db()
print(f'\nEstado DESPUÉS: {config.estado}')
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
EOF
```

