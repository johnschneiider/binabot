# Corrección: Balance del Bot Inverso desde Deriv

## Problema Identificado

El balance del bot inverso mostraba $100.00 porque:
1. El script `INICIALIZAR_BOT_INVERSO.sh` establecía un valor fijo de $100.00
2. La función `sincronizar_balance_desde_api` solo actualizaba si el balance era > 0, pero si ya estaba en $100.00, no se sincronizaba desde Deriv

## Solución Aplicada

### 1. Modificación de `sincronizar_balance_desde_api`

Ahora **SIEMPRE** sincroniza el balance desde Deriv, incluso si ya tiene un valor:
- Actualiza el balance desde Deriv en cada llamada
- Inicializa las bases (meta_base, stop_loss_base) solo si es la primera vez
- Mantiene la lógica de trailing stop loss

### 2. Actualización del Script de Inicialización

El script `INICIALIZAR_BOT_INVERSO.sh` ahora:
- **Sincroniza** el balance desde Deriv en lugar de establecer un valor fijo
- Usa `gestor.sincronizar_balance_desde_api()` para obtener el balance real

## Pasos para Corregir en la VPS

### Opción 1: Ejecutar el Script Actualizado

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
git pull origin main
bash INICIALIZAR_BOT_INVERSO.sh
```

### Opción 2: Sincronizar Manualmente

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
python manage.py shell << EOF
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.sincronizar_balance_desde_api()
config = gestor.configuracion
print(f'Balance sincronizado: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
EOF
```

### Opción 3: Verificar Balance Actual en DB

```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
print(f'Balance actual en DB: \${config.balance_actual}')
print(f'Stop Loss: \${config.stop_loss_actual}')
"
```

## Verificación

Después de sincronizar, verifica que:

1. **El balance coincide con Deriv:**
   ```bash
   python manage.py shell -c "
   from integracion_deriv.client import obtener_balance_sync
   from trading_inverso.models import ConfiguracionBotInverso
   balance_deriv = obtener_balance_sync().get('balance', 0)
   config = ConfiguracionBotInverso.obtener()
   print(f'Balance en Deriv: \${balance_deriv}')
   print(f'Balance en DB: \${config.balance_actual}')
   print(f'¿Coinciden? {float(balance_deriv) == float(config.balance_actual)}')
   "
   ```

2. **El dashboard muestra el balance correcto:**
   - Abre `/bot-inverso/` en el navegador
   - El balance debe coincidir con el de Deriv
   - Si no coincide, limpia el cache del navegador (Ctrl+Shift+Delete)

## Comportamiento Esperado

- **Balance siempre sincronizado**: Cada vez que se consulta el estado, se sincroniza desde Deriv
- **Sin valores fijos**: No hay más valores hardcodeados de $100.00
- **Inicialización automática**: Si el balance es 0, se sincroniza desde Deriv al iniciar

## Notas

- El balance se sincroniza automáticamente en:
  - Cada consulta a `/api/trading-inverso/estado/`
  - Cada actualización WebSocket (cada 10 segundos)
  - Cada ciclo del bot inverso (cada 5 segundos por defecto)

