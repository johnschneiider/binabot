# Corrección: Stop Loss Incoherente con Balance

## Problema Identificado

El stop loss ($98.00) era mayor que el balance actual ($87.29), lo cual es incorrecto. Esto puede ocurrir cuando:
- El balance se inicializó con un valor mayor (ej: $100.00)
- El stop loss se calculó al 98% de ese balance ($98.00)
- El balance luego bajó (ej: a $87.29)
- El stop loss no se actualizó porque la lógica de trailing solo permite que suba

## Solución Aplicada

Se corrigió la lógica de sincronización del stop loss para que:

1. **Corrección de inconsistencia**: Si el stop loss actual es mayor que el balance, se recalcula al 98% del balance actual
2. **Trailing stop loss**: Si el balance sube, el stop loss sube (solo sube, nunca baja)
3. **Stop loss fijo en pérdidas**: Si el balance baja, el stop loss NO baja (se mantiene fijo como protección)

### Código Corregido

```python
# Lógica de stop loss:
# 1. Si el stop loss actual es mayor que el balance, recalcular (corrección de inconsistencia)
# 2. Si el balance sube, aplicar trailing stop loss (solo sube)
# 3. Si el balance baja, el stop loss NO baja (se mantiene fijo como protección)
if self.configuracion.estado == ConfiguracionBotInverso.Estado.OPERANDO:
    nuevo_stop_loss = self.configuracion.calcular_stop_loss(balance)
    
    # CORRECCIÓN: Si el stop loss actual es mayor que el balance, recalcular
    if self.configuracion.stop_loss_actual > balance:
        self.configuracion.stop_loss_actual = nuevo_stop_loss
        self.configuracion.balance_stop_loss_base = balance
    # Trailing stop loss: solo sube, nunca baja
    elif nuevo_stop_loss > self.configuracion.stop_loss_actual:
        self.configuracion.stop_loss_actual = nuevo_stop_loss
        self.configuracion.balance_stop_loss_base = balance
    # Si el balance baja, el stop_loss_actual NO cambia (se mantiene fijo)
```

## Pasos para Aplicar en VPS

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
git pull origin main

# Sincronizar balance y corregir stop loss
python manage.py shell << EOF
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.sincronizar_balance_desde_api()
config = gestor.configuracion
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
print(f'Stop Loss debería ser: \${config.calcular_stop_loss(config.balance_actual)}')
print(f'¿Es coherente? {config.stop_loss_actual <= config.balance_actual}')
EOF

# Reiniciar servicios
sudo systemctl restart binabot.service
sudo systemctl restart binabot-inverso.service
```

## Verificación

```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
stop_loss_esperado = config.calcular_stop_loss(config.balance_actual)
print(f'Balance: \${config.balance_actual}')
print(f'Stop Loss actual: \${config.stop_loss_actual}')
print(f'Stop Loss esperado (98%): \${stop_loss_esperado}')
print(f'¿Es coherente? {config.stop_loss_actual <= config.balance_actual}')
print(f'¿Está correcto? {abs(float(config.stop_loss_actual) - float(stop_loss_esperado)) < 0.01 or config.stop_loss_actual > stop_loss_esperado}')
"
```

## Comportamiento Esperado

- **Stop loss nunca mayor que balance**: Si el stop loss es mayor que el balance, se recalcula
- **Trailing stop loss**: Cuando el balance sube, el stop loss sube (solo sube)
- **Stop loss fijo en pérdidas**: Cuando el balance baja, el stop loss se mantiene fijo

## Ejemplo

- Balance inicial: $100.00 → Stop Loss: $98.00 ✅
- Balance baja a: $87.29 → Stop Loss: $85.55 (recalculado) ✅
- Balance sube a: $90.00 → Stop Loss: $88.20 (trailing) ✅
- Balance baja a: $89.00 → Stop Loss: $88.20 (fijo, no baja) ✅

