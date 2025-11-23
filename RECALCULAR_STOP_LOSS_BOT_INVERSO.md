# Recalcular Stop Loss del Bot Inverso

## Problema

El stop loss del bot inverso puede estar calculado con el porcentaje anterior (2%) en lugar del nuevo (5%). Esto puede pasar si:
- El stop loss se calculó antes de cambiar el porcentaje
- El código se actualizó pero el valor en la base de datos no se recalculó

## Solución Automática

El código ahora detecta automáticamente si el stop loss no coincide con el cálculo correcto y lo recalcula.

## Solución Manual (Si es Necesario)

```bash
python manage.py shell << EOF
from trading_inverso.models import ConfiguracionBotInverso
from decimal import Decimal

config = ConfiguracionBotInverso.obtener()

print(f'Balance base: \${config.balance_stop_loss_base}')
print(f'Stop Loss actual: \${config.stop_loss_actual}')
print(f'Stop Loss esperado (5%): \${config.calcular_stop_loss(config.balance_stop_loss_base)}')

# Recalcular stop loss
nuevo_stop_loss = config.calcular_stop_loss(config.balance_stop_loss_base)
config.stop_loss_actual = nuevo_stop_loss
config.save(update_fields=['stop_loss_actual'])

print(f'\nStop Loss actualizado: \${config.stop_loss_actual}')
EOF
```

## Verificación

```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
stop_loss_esperado = config.calcular_stop_loss(config.balance_stop_loss_base)
print(f'Balance base: \${config.balance_stop_loss_base}')
print(f'Stop Loss actual: \${config.stop_loss_actual}')
print(f'Stop Loss esperado (5%): \${stop_loss_esperado}')
print(f'¿Coinciden? {abs(float(config.stop_loss_actual) - float(stop_loss_esperado)) < 0.01}')
"
```

## Ejemplo de Cálculo

- Balance base: $87.35
- Stop Loss (5%): $87.35 * 0.95 = **$82.98**
- Stop Loss (2%): $87.35 * 0.98 = $85.60 ❌ (incorrecto)

El stop loss debe ser **$82.98** (95% del balance base), no $85.60.

