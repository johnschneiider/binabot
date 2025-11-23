# Comando para Reanudar el Bot Inverso

## Comando Rápido

```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
config.reanudar()
print(f'Bot inverso reanudado. Estado: {config.estado}')
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
"
```

## Verificar y Reanudar Ambos Bots

```bash
python manage.py shell << EOF
from core.models import ConfiguracionBot
from trading_inverso.models import ConfiguracionBotInverso

# Reanudar bot principal
config_principal = ConfiguracionBot.obtener()
if config_principal.estado == 'pausado':
    config_principal.reanudar()
    print('✅ Bot principal reanudado')
else:
    print(f'Bot principal ya está: {config_principal.estado}')

# Reanudar bot inverso
config_inverso = ConfiguracionBotInverso.obtener()
if config_inverso.estado == 'pausado':
    config_inverso.reanudar()
    print('✅ Bot inverso reanudado')
else:
    print(f'Bot inverso ya está: {config_inverso.estado}')

# Verificar estado final
config_principal.refresh_from_db()
config_inverso.refresh_from_db()

print('\nESTADO FINAL:')
print(f'Bot Principal: {config_principal.estado} | Balance: \${config_principal.balance_actual} | Stop Loss: \${config_principal.stop_loss_actual}')
print(f'Bot Inverso: {config_inverso.estado} | Balance: \${config_inverso.balance_actual} | Stop Loss: \${config_inverso.stop_loss_actual}')
EOF
```

## Verificar Por Qué Está Pausado

```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
print(f'Estado: {config.estado}')
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
print(f'Pausado desde: {config.pausado_desde}')
print(f'Pausa finaliza: {config.pausa_finaliza}')
if config.balance_actual > config.stop_loss_actual:
    print('✅ Balance está por encima del stop loss. Se puede reanudar.')
else:
    print('⚠️ Balance está por debajo del stop loss.')
"
```

