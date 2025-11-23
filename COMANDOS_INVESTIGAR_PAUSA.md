# Comandos para Investigar Por Qué el Bot se Pausó Estando en Ganancia

## Análisis del Problema

Según los logs y la investigación:
- El bot se pausó a las **01:04:50**
- La última operación registrada ANTES de la pausa fue a las **01:03:47** (RDBEAR PUT - loss)
- Las operaciones ganadas fueron a las **01:50:46** y **01:52:55** (DESPUÉS de la pausa)
- El balance actual ($87.00) está POR ENCIMA del stop loss ($86.02)
- El bot se pausó incorrectamente

## Comandos de Investigación

### 1. Comando Completo de Investigación

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
git pull origin main

python manage.py investigar_pausa
```

### 2. Buscar Momento Exacto de Pausa

```bash
python manage.py buscar_momento_pausa
```

### 3. Ver Logs del Momento Exacto de la Pausa

```bash
# Ver logs alrededor de las 01:04:50 (momento de pausa)
sudo journalctl -u binabot-loop.service --since "2025-11-23 00:55:00" --until "2025-11-23 01:10:00" --no-pager | grep -v "Estado: OPERANDO" | tail -100
```

### 4. Buscar Mensajes de Error o Pausa en los Logs

```bash
# Buscar todos los mensajes relacionados con pausa, stop loss, balance
sudo journalctl -u binabot-loop.service --since "2025-11-23 00:50:00" --until "2025-11-23 01:10:00" --no-pager | grep -E "pausa|pausado|stop|balance|sincronizar|verificar|error|exception" -i
```

### 5. Ver Operaciones Justo Antes de la Pausa

```bash
python manage.py shell << 'EOF'
from core.models import ConfiguracionBot
from historial.models import Operacion
from django.utils import timezone
from datetime import timedelta

config = ConfiguracionBot.obtener()

if config.pausado_desde:
    # Operaciones en los 30 minutos antes de la pausa
    desde = config.pausado_desde - timedelta(minutes=30)
    hasta = config.pausado_desde + timedelta(minutes=5)
    
    ops = Operacion.objetos.reales().filter(
        hora_inicio__gte=desde,
        hora_inicio__lte=hasta
    ).order_by('hora_inicio')
    
    print(f"Operaciones entre {desde.strftime('%H:%M:%S')} y {hasta.strftime('%H:%M:%S')}:")
    print(f"Total: {ops.count()}\n")
    
    balance_simulado = config.balance_actual
    for op in reversed(ops):
        if op.hora_inicio < config.pausado_desde:
            if op.resultado == 'win':
                balance_simulado -= op.beneficio
            else:
                balance_simulado += abs(op.beneficio)
    
    print(f"Balance estimado al inicio: ${balance_simulado:.2f}\n")
    
    balance_actual = balance_simulado
    for op in ops:
        tiempo_relativo = (op.hora_inicio - config.pausado_desde).total_seconds() / 60
        
        if op.resultado == 'win':
            balance_despues = balance_actual + op.beneficio
        else:
            balance_despues = balance_actual - abs(op.beneficio)
        
        stop_loss = config.calcular_stop_loss(config.balance_stop_loss_base)
        if balance_despues > config.balance_stop_loss_base:
            stop_loss = config.calcular_stop_loss(balance_despues)
        
        print(f"{op.hora_inicio.strftime('%H:%M:%S')} | {op.resultado.upper()} | ${op.beneficio:.2f}")
        print(f"  Balance: ${balance_actual:.2f} → ${balance_despues:.2f} | Stop Loss: ${stop_loss:.2f} | {tiempo_relativo:+.1f} min")
        
        if balance_actual <= stop_loss or balance_despues <= stop_loss:
            print(f"  ⚠️  Balance <= Stop Loss - ESTO CAUSÓ LA PAUSA")
        
        balance_actual = balance_despues
EOF
```

### 6. Verificar Si Hay Operaciones No Registradas

```bash
# Ver si hay operaciones que no están en la BD pero sí en Deriv
python manage.py shell -c "
from integracion_deriv.client import obtener_balance_sync
from core.models import ConfiguracionBot
from historial.models import Operacion
from django.utils import timezone
from datetime import timedelta

config = ConfiguracionBot.obtener()

# Balance de Deriv
respuesta = obtener_balance_sync()
balance_deriv = respuesta.get('balance', {}).get('balance', 0)

# Balance esperado desde operaciones
ultima_op = Operacion.objetos.reales().order_by('-hora_inicio').first()
if ultima_op:
    print(f'Última operación: {ultima_op.hora_inicio} | {ultima_op.resultado} | ${ultima_op.beneficio:.2f}')
    print(f'Balance en Deriv: ${balance_deriv:.2f}')
    print(f'Balance en BD: ${config.balance_actual:.2f}')
    diferencia = abs(float(balance_deriv - config.balance_actual))
    if diferencia > 0.10:
        print(f'⚠️  Diferencia: ${diferencia:.2f} - Puede haber operaciones no registradas')
"
```

### 7. Ver Logs Completos Sin Filtrar

```bash
# Ver TODOS los logs alrededor de la pausa (sin filtrar)
sudo journalctl -u binabot-loop.service --since "2025-11-23 01:00:00" --until "2025-11-23 01:10:00" --no-pager
```

## Posibles Causas

1. **Sincronización de balance desactualizada**: El balance en la BD no coincidía con Deriv en el momento de la pausa
2. **Operación no registrada**: Hubo una pérdida que no se registró en la BD pero sí afectó el balance
3. **Bug en la lógica**: El bot se pausó incorrectamente por un error en el código (ya corregido)
4. **Pausa manual**: Se pausó desde el admin o la API

## Solución Temporal

Si el bot está pausado incorrectamente:

```bash
# Reanudar el bot
python manage.py shell -c "from core.models import ConfiguracionBot; ConfiguracionBot.obtener().reanudar(); print('Bot reanudado')"

# Reiniciar el servicio para aplicar la corrección
sudo systemctl restart binabot-loop.service
```

## Verificación Post-Corrección

Después de aplicar la corrección, el bot NO debería pausarse incorrectamente durante sincronizaciones. La pausa solo debería ocurrir:
1. Después de una pérdida registrada
2. Cuando el balance realmente cae por debajo del stop loss
3. NO durante sincronizaciones de balance

