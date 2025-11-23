# Verificar que el Bot Inverso está Funcionando

## ✅ Estado Actual

El servicio está **activo y corriendo**:
- Estado: `active (running)`
- PID: 366234
- Habilitado: `enabled`

## Verificación Rápida

### 1. Ver Logs en Tiempo Real

```bash
journalctl -u binabot-inverso.service -f
```

Deberías ver:
```
Monitoreando operaciones del bot principal...
```

### 2. Verificar Estado del Bot

```bash
python manage.py shell -c '
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
print(f"Estado: {config.estado}")
print(f"Balance: ${config.balance_actual}")
print(f"En operación: {config.en_operacion}")
'
```

### 3. Ver Últimas Operaciones del Bot Principal

```bash
python manage.py shell -c '
from historial.models import Operacion
ops = Operacion.objetos.reales().order_by("-hora_inicio")[:5]
for op in ops:
    print(f"{op.activo} {op.direccion} - {op.resultado} - ${op.beneficio}")
'
```

### 4. Verificar que el Bot Inverso Detecta Operaciones

Cuando el bot principal ejecute una operación, en los logs del bot inverso deberías ver:

```
🔄 Nueva operación principal detectada: [ACTIVO] [DIRECCIÓN] ([RESULTADO])
🔄 Ejecutando operación INVERSA: [ACTIVO] [DIRECCIÓN_INVERSA] (Principal: [DIRECCIÓN])
✓ Operación INVERSA ejecutada: [CONTRACT_ID] [RESULTADO] beneficio=[BENEFICIO]
```

## Comandos Útiles

### Reiniciar el Bot Inverso

```bash
sudo systemctl restart binabot-inverso.service
```

### Detener el Bot Inverso

```bash
sudo systemctl stop binabot-inverso.service
```

### Ver Estado del Servicio

```bash
sudo systemctl status binabot-inverso.service
```

### Ver Logs de las Últimas 10 Minutos

```bash
journalctl -u binabot-inverso.service --since "10 minutes ago" --no-pager
```

### Ver Últimas Operaciones Inversas

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
ops = OperacionInversa.objetos.reales().order_by("-hora_inicio")[:10]
for op in ops:
    print(f"{op.activo} {op.direccion} - {op.resultado} - ${op.beneficio} - Principal: {op.operacion_principal_id}")
'
```

## Cómo Funciona

1. **Monitoreo**: El bot inverso verifica cada 5 segundos si hay nuevas operaciones del bot principal
2. **Detección**: Cuando detecta una operación nueva (completada, no simulada):
   - Invierte la dirección (CALL → PUT, PUT → CALL)
   - Ejecuta la operación en el mismo activo
   - Guarda la operación en su base de datos
3. **Registro**: Cada operación inversa tiene referencia a la operación principal

## Verificar que Está Funcionando Correctamente

### Test Manual

1. Espera a que el bot principal ejecute una operación
2. Inmediatamente revisa los logs del bot inverso:
   ```bash
   journalctl -u binabot-inverso.service --since "1 minute ago" --no-pager
   ```
3. Deberías ver que detectó y ejecutó la operación inversa

### Ver Operaciones Inversas en la Base de Datos

```bash
python manage.py shell -c '
from trading_inverso.models import OperacionInversa
total = OperacionInversa.objetos.reales().count()
ganadas = OperacionInversa.objetos.reales().filter(resultado="win").count()
print(f"Total operaciones inversas: {total}")
print(f"Ganadas: {ganadas}")
if total > 0:
    print(f"Winrate: {(ganadas/total*100):.1f}%")
'
```

## Solución de Problemas

### El bot inverso no detecta operaciones

1. Verificar que el bot principal está ejecutando operaciones
2. Verificar que las operaciones no son simuladas
3. Verificar que las operaciones están completadas (no pendientes)
4. Revisar logs: `journalctl -u binabot-inverso.service -f`

### El bot inverso no ejecuta operaciones

1. Verificar balance: `config.balance_actual >= monto_trade`
2. Verificar estado: `config.estado == "operando"`
3. Verificar que no está en operación: `config.en_operacion == False`
4. Verificar stop loss: `config.balance_actual > config.stop_loss_actual`

### Reanudar Bot Inverso (si está pausado)

```bash
python manage.py shell -c '
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.configuracion.reanudar()
print("Bot inverso reanudado")
'
```

