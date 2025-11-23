# Investigación: Por Qué el Bot Inverso No Opera

## Problema Identificado

El bot inverso **NO opera** porque el bot principal está **PAUSADO**. 

### Lógica del Bot Inverso

El bot inverso funciona así:
1. **Monitorea** las operaciones del bot principal
2. Cuando detecta una **nueva operación** del bot principal, ejecuta la dirección opuesta
3. Si el bot principal está **pausado**, no genera nuevas operaciones
4. Sin nuevas operaciones, el bot inverso **no tiene nada que invertir**

### Código Relevante

```python
# En ejecutar_bot_inverso.py
if estado.estado == gestor.configuracion.Estado.OPERANDO:
    # Buscar nuevas operaciones del bot principal
    operaciones_nuevas = OperacionPrincipal.objetos.reales().filter(
        id__gt=ultima_operacion_id if ultima_operacion_id else 0
    ).order_by('id')
    
    for operacion_principal in operaciones_nuevas:
        # Ejecutar operación inversa
        operacion_inversa = motor.ejecutar_ciclo_inverso(operacion_principal)
```

## Solución: Reanudar el Bot Principal

Para que el bot inverso opere, primero debes reanudar el bot principal:

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
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
"
```

## Verificar Estado de Ambos Bots

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
from trading_inverso.models import ConfiguracionBotInverso

config_principal = ConfiguracionBot.obtener()
config_inverso = ConfiguracionBotInverso.obtener()

print('BOT PRINCIPAL:')
print(f'  Estado: {config_principal.estado}')
print(f'  Balance: \${config_principal.balance_actual}')
print(f'  Stop Loss: \${config_principal.stop_loss_actual}')
print(f'  En operación: {config_principal.en_operacion}')

print('\nBOT INVERSO:')
print(f'  Estado: {config_inverso.estado}')
print(f'  Balance: \${config_inverso.balance_actual}')
print(f'  Stop Loss: \${config_inverso.stop_loss_actual}')
print(f'  En operación: {config_inverso.en_operacion}')

print('\nÚLTIMA OPERACIÓN DEL BOT PRINCIPAL:')
from historial.models import Operacion
ultima = Operacion.objetos.reales().order_by('-hora_inicio').first()
if ultima:
    print(f'  {ultima.hora_inicio} | {ultima.activo} {ultima.direccion} | {ultima.resultado}')
else:
    print('  No hay operaciones')
"
```

## Verificar Logs del Bot Inverso

```bash
# Ver logs del servicio del bot inverso
sudo journalctl -u binabot-inverso.service --since "10 minutes ago" --no-pager | tail -50
```

## Flujo Esperado

1. **Bot Principal** genera una operación (ej: CALL en R_10)
2. **Bot Inverso** detecta la nueva operación
3. **Bot Inverso** ejecuta la dirección opuesta (PUT en R_10)
4. Ambos bots esperan el resultado de sus operaciones
5. Se repite el ciclo

## Si el Bot Inverso Sigue Sin Operar

Verifica:

1. **¿El bot principal está operando?**
   ```bash
   python manage.py shell -c "from core.models import ConfiguracionBot; print(ConfiguracionBot.obtener().estado)"
   ```

2. **¿El bot inverso está operando?**
   ```bash
   python manage.py shell -c "from trading_inverso.models import ConfiguracionBotInverso; print(ConfiguracionBotInverso.obtener().estado)"
   ```

3. **¿Hay nuevas operaciones del bot principal?**
   ```bash
   python manage.py shell -c "
   from historial.models import Operacion
   from django.utils import timezone
   from datetime import timedelta
   desde = timezone.now() - timedelta(minutes=5)
   nuevas = Operacion.objetos.reales().filter(hora_inicio__gte=desde)
   print(f'Operaciones nuevas (últimos 5 min): {nuevas.count()}')
   for op in nuevas:
       print(f'  {op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado}')
   "
   ```

4. **¿El servicio del bot inverso está corriendo?**
   ```bash
   sudo systemctl status binabot-inverso.service
   ```

