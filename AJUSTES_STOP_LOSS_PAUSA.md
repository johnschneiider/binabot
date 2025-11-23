# Ajustes de Stop Loss y Tiempo de Pausa

## Cambios Aplicados

### Bot Inverso
- **Stop Loss**: Cambiado de 2% a **5%** del capital
- **Tiempo de Pausa**: Cambiado de 24 horas a **1 hora**

### Bot Principal
- **Stop Loss**: Mantiene **2%** del capital
- **Tiempo de Pausa**: Cambiado de 24 horas a **1 hora**

## Detalles Técnicos

### Bot Inverso (`trading_inverso/models.py`)

```python
STOP_LOSS_PORCENTAJE = Decimal("0.05")  # 5% para bot inverso

def calcular_stop_loss(self, balance: Decimal) -> Decimal:
    """Calcula el stop loss al 95% del balance (5% de pérdida máxima)."""
    return (balance * (Decimal("1") - self.STOP_LOSS_PORCENTAJE)).quantize(Decimal("0.01"))

def pausar(self, horas: int = 1) -> None:
    """Pausa el bot por N horas. Por defecto 1 hora."""
```

### Bot Principal (`core/models.py`)

```python
STOP_LOSS_PORCENTAJE = Decimal("0.02")  # 2% para bot principal (sin cambios)

def pausar(self, horas: int = 1) -> None:
    """Pausa el bot por N horas. Por defecto 1 hora."""
```

## Ejemplos de Cálculo

### Bot Inverso (5% stop loss)
- Balance: $100.00 → Stop Loss: $95.00 (5% de pérdida máxima)
- Balance: $87.17 → Stop Loss: $82.81 (5% de pérdida máxima)

### Bot Principal (2% stop loss)
- Balance: $100.00 → Stop Loss: $98.00 (2% de pérdida máxima)
- Balance: $87.17 → Stop Loss: $85.43 (2% de pérdida máxima)

## Comportamiento de Pausa

Cuando el balance alcanza el stop loss:
1. El bot se pausa automáticamente
2. La pausa dura **1 hora** (no 24 horas)
3. Después de 1 hora, el bot se reactiva automáticamente
4. El stop loss se recalcula al 95% (bot inverso) o 98% (bot principal) del nuevo balance

## Pasos para Aplicar en VPS

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
git pull origin main

# Verificar cambios
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
from core.models import ConfiguracionBot

config_inverso = ConfiguracionBotInverso.obtener()
config_principal = ConfiguracionBot.obtener()

print('BOT INVERSO:')
print(f'  Stop Loss %: {config_inverso.STOP_LOSS_PORCENTAJE * 100}%')
print(f'  Balance: \${config_inverso.balance_actual}')
print(f'  Stop Loss: \${config_inverso.calcular_stop_loss(config_inverso.balance_actual)}')

print('\nBOT PRINCIPAL:')
print(f'  Stop Loss %: {config_principal.STOP_LOSS_PORCENTAJE * 100}%')
print(f'  Balance: \${config_principal.balance_actual}')
print(f'  Stop Loss: \${config_principal.calcular_stop_loss(config_principal.balance_actual)}')
"

# Reiniciar servicios
sudo systemctl restart binabot.service
sudo systemctl restart binabot-inverso.service
```

## Verificación

Después de aplicar los cambios, verifica que:

1. **Bot Inverso**: Stop loss = 95% del balance (5% de pérdida máxima)
2. **Bot Principal**: Stop loss = 98% del balance (2% de pérdida máxima)
3. **Ambos bots**: Pausa de 1 hora cuando se alcanza el stop loss

## Notas

- El stop loss se recalcula automáticamente cuando el balance cambia
- La pausa se activa automáticamente cuando `balance_actual <= stop_loss_actual`
- El bot se reactiva automáticamente después de 1 hora si no hay mejor horario configurado

