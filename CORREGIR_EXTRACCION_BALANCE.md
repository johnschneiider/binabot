# Corrección: Extracción de Balance desde Deriv

## Problema Identificado

La respuesta de `obtener_balance_sync()` tiene una estructura anidada:

```python
{
    "balance": {
        "balance": 85.67,
        "currency": "USD",
        "loginid": "CR9822432"
    }
}
```

El código en `trading_inverso/services.py` estaba intentando acceder directamente a `respuesta.get("balance", 0)`, lo que devolvía el diccionario completo en lugar del número.

## Solución Aplicada

Se corrigió la extracción del balance para que coincida con la implementación en `core/services.py`:

```python
# ANTES (incorrecto):
balance = Decimal(str(respuesta.get("balance", 0)))

# DESPUÉS (correcto):
balance_info = respuesta.get("balance")
if not balance_info:
    return
balance = Decimal(str(balance_info.get("balance", "0")))
```

## Pasos para Aplicar en VPS

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate

# Resolver conflicto de merge si existe
git stash
git pull origin main
git stash pop  # Si hay cambios locales que quieres mantener

# O simplemente descartar cambios locales en INICIALIZAR_BOT_INVERSO.sh
git checkout -- INICIALIZAR_BOT_INVERSO.sh
git pull origin main

# Sincronizar balance correctamente
python manage.py shell << EOF
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.sincronizar_balance_desde_api()
config = gestor.configuracion
print(f'Balance sincronizado: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
EOF

# Reiniciar servicios
sudo systemctl restart binabot.service
sudo systemctl restart binabot-inverso.service
```

## Verificación Correcta

```bash
python manage.py shell -c "
from integracion_deriv.client import obtener_balance_sync
from trading_inverso.models import ConfiguracionBotInverso

# Obtener balance de Deriv
respuesta_deriv = obtener_balance_sync()
balance_info = respuesta_deriv.get('balance', {})
balance_deriv = balance_info.get('balance', 0)

# Obtener balance de DB
config = ConfiguracionBotInverso.obtener()
balance_db = float(config.balance_actual)

print(f'Balance en Deriv: \${balance_deriv}')
print(f'Balance en DB: \${balance_db}')
print(f'¿Coinciden? {abs(balance_deriv - balance_db) < 0.01}')
"
```

## Resultado Esperado

- El balance se sincroniza correctamente desde Deriv
- El balance en la base de datos coincide con el de Deriv
- El dashboard muestra el balance real de la cuenta

