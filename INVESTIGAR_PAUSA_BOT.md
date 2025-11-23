# Investigar Por Qué el Bot se Pausa Estando en Ganancia

## Comandos de Investigación

### 1. Ver Estado Actual del Bot

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate

python manage.py shell -c "
from core.models import ConfiguracionBot
from django.utils import timezone

config = ConfiguracionBot.obtener()
print('=== ESTADO ACTUAL DEL BOT ===')
print(f'Estado: {config.estado}')
print(f'Balance actual: \${config.balance_actual:.2f}')
print(f'Balance meta base: \${config.balance_meta_base:.2f}')
print(f'Balance stop loss base: \${config.balance_stop_loss_base:.2f}')
print(f'Stop loss actual: \${config.stop_loss_actual:.2f}')
print(f'Meta actual: \${config.meta_actual:.2f}')
print(f'Ganancia acumulada: \${config.ganancia_acumulada:.2f}')
print(f'Pérdida acumulada: \${config.perdida_acumulada:.2f}')
print(f'Pausado desde: {config.pausado_desde}')
print(f'Pausa finaliza: {config.pausa_finaliza}')
if config.pausa_finaliza:
    tiempo_restante = config.pausa_finaliza - timezone.now()
    print(f'Tiempo restante: {tiempo_restante}')
"
```

### 2. Ver Últimas Operaciones y Su Relación con la Pausa

```bash
python manage.py shell -c "
from historial.models import Operacion
from core.models import ConfiguracionBot
from django.utils import timezone
from datetime import timedelta

config = ConfiguracionBot.obtener()

# Últimas 10 operaciones
ops = Operacion.objetos.reales().order_by('-hora_inicio')[:10]
print('=== ÚLTIMAS 10 OPERACIONES ===')
for op in ops:
    tiempo_desde = timezone.now() - op.hora_inicio
    print(f'{op.hora_inicio.strftime(\"%Y-%m-%d %H:%M:%S\")} | {op.activo} {op.direccion} | {op.resultado} | \${op.beneficio:.2f} | Hace: {tiempo_desde}')

# Verificar si la pausa ocurrió después de una ganancia
if config.pausado_desde:
    print(f'\n=== ANÁLISIS DE PAUSA ===')
    print(f'Pausado desde: {config.pausado_desde}')
    
    # Operación justo antes de la pausa
    op_antes_pausa = Operacion.objetos.reales().filter(
        hora_inicio__lte=config.pausado_desde
    ).order_by('-hora_inicio').first()
    
    if op_antes_pausa:
        print(f'Última operación antes de pausa:')
        print(f'  {op_antes_pausa.hora_inicio} | {op_antes_pausa.activo} {op_antes_pausa.direccion} | {op_antes_pausa.resultado} | \${op_antes_pausa.beneficio:.2f}')
        tiempo_diferencia = config.pausado_desde - op_antes_pausa.hora_inicio
        print(f'  Tiempo entre operación y pausa: {tiempo_diferencia}')
"
```

### 3. Buscar en el Código Dónde se Llama a pausar()

```bash
# Ver todos los lugares donde se llama pausar
grep -r "\.pausar\|pausar(" core/ trading/ --include="*.py" | grep -v ".pyc" | grep -v "__pycache__"
```

### 4. Ver Logs del Bot para Encontrar el Momento de la Pausa

```bash
# Ver logs alrededor del momento de la pausa
python manage.py shell -c "
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
if config.pausado_desde:
    print(f'Buscar logs alrededor de: {config.pausado_desde}')
    print(f'Comando: sudo journalctl -u binabot-loop.service --since \"{config.pausado_desde.strftime(\"%Y-%m-%d %H:%M:%S\")}\" --until \"{(config.pausado_desde + timedelta(minutes=5)).strftime(\"%Y-%m-%d %H:%M:%S\")}\" --no-pager')
"
```

### 5. Verificar Lógica de Stop Loss y Meta

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
from decimal import Decimal

config = ConfiguracionBot.obtener()

print('=== VERIFICACIÓN DE LÓGICA ===')
print(f'Balance actual: \${config.balance_actual:.2f}')
print(f'Stop loss actual: \${config.stop_loss_actual:.2f}')
print(f'Balance stop loss base: \${config.balance_stop_loss_base:.2f}')

# Calcular stop loss esperado
stop_loss_esperado = config.calcular_stop_loss(config.balance_stop_loss_base)
print(f'Stop loss esperado (2% de base): \${stop_loss_esperado:.2f}')

# Verificar si el balance está por encima del stop loss
if config.balance_actual > config.stop_loss_actual:
    print('✅ Balance está por encima del stop loss')
else:
    print('❌ Balance está en o por debajo del stop loss')
    print(f'   Diferencia: \${config.balance_actual - config.stop_loss_actual:.2f}')

# Verificar meta
meta_esperada = config.calcular_meta()
print(f'Meta esperada: \${meta_esperada:.2f}')
print(f'Meta actual: \${config.meta_actual:.2f}')
"
```

### 6. Ver Historial de Cambios de Estado

```bash
# Ver si hay algún log o registro de cambios de estado
python manage.py shell -c "
from historial.models import Operacion
from core.models import ConfiguracionBot
from django.utils import timezone
from datetime import timedelta

config = ConfiguracionBot.obtener()

# Ver operaciones en la hora antes de la pausa
if config.pausado_desde:
    desde = config.pausado_desde - timedelta(hours=1)
    hasta = config.pausado_desde + timedelta(minutes=5)
    
    ops_periodo = Operacion.objetos.reales().filter(
        hora_inicio__gte=desde,
        hora_inicio__lte=hasta
    ).order_by('hora_inicio')
    
    print(f'=== OPERACIONES EN EL PERÍODO DE PAUSA ===')
    print(f'Desde: {desde} hasta: {hasta}')
    print(f'Total operaciones: {ops_periodo.count()}')
    
    ganadas = ops_periodo.filter(resultado='win')
    perdidas = ops_periodo.filter(resultado='loss')
    
    print(f'Ganadas: {ganadas.count()}')
    print(f'Perdidas: {perdidas.count()}')
    
    beneficio_total = sum(op.beneficio for op in ops_periodo)
    print(f'Beneficio total del período: \${beneficio_total:.2f}')
    
    print('\nOperaciones:')
    for op in ops_periodo:
        print(f'  {op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | \${op.beneficio:.2f}')
"
```

### 7. Verificar Si Hay Alguna Condición Especial en el Código

```bash
# Buscar condiciones que puedan causar pausa
python manage.py shell -c "
# Revisar la lógica de registrar_ganancia y registrar_perdida
from core.models import ConfiguracionBot
import inspect

config = ConfiguracionBot.obtener()

# Ver el código fuente de los métodos relevantes
print('=== CÓDIGO DE REGISTRAR_GANANCIA ===')
print(inspect.getsource(config.registrar_ganancia))

print('\n=== CÓDIGO DE REGISTRAR_PÉRDIDA ===')
print(inspect.getsource(config.registrar_perdida))

print('\n=== CÓDIGO DE PAUSAR ===')
print(inspect.getsource(config.pausar))
"
```

### 8. Ver Logs del Sistema en Tiempo Real

```bash
# Ver logs en tiempo real del bot
sudo journalctl -u binabot-loop.service -f

# O ver logs de las últimas horas
sudo journalctl -u binabot-loop.service --since "2 hours ago" --no-pager | grep -E "(pausa|pausado|ganancia|perdida|stop|meta)" -i
```

### 9. Comando Completo de Diagnóstico

```bash
python manage.py shell << 'EOF'
from core.models import ConfiguracionBot
from historial.models import Operacion
from django.utils import timezone
from datetime import timedelta

config = ConfiguracionBot.obtener()

print("="*80)
print("INVESTIGACIÓN COMPLETA DE PAUSA")
print("="*80)

print(f"\n1. ESTADO ACTUAL:")
print(f"   Estado: {config.estado}")
print(f"   Balance: \${config.balance_actual:.2f}")
print(f"   Stop Loss: \${config.stop_loss_actual:.2f}")
print(f"   Pausado desde: {config.pausado_desde}")
print(f"   Pausa finaliza: {config.pausa_finaliza}")

if config.pausado_desde:
    print(f"\n2. ÚLTIMAS OPERACIONES ANTES DE LA PAUSA:")
    desde = config.pausado_desde - timedelta(hours=2)
    ops = Operacion.objetos.reales().filter(
        hora_inicio__gte=desde,
        hora_inicio__lte=config.pausado_desde
    ).order_by('-hora_inicio')[:10]
    
    for op in ops:
        tiempo_antes = config.pausado_desde - op.hora_inicio
        print(f"   {op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | \${op.beneficio:.2f} | {tiempo_antes} antes de pausa")
    
    # Última operación antes de pausa
    ultima = ops.first() if ops else None
    if ultima:
        print(f"\n3. ÚLTIMA OPERACIÓN ANTES DE PAUSA:")
        print(f"   {ultima.hora_inicio} | {ultima.activo} {ultima.direccion} | {ultima.resultado} | \${ultima.beneficio:.2f}")
        if ultima.resultado == 'win':
            print(f"   ⚠️  ÚLTIMA OPERACIÓN FUE GANADA - Esto no debería causar pausa")
        
        # Calcular balance esperado después de esta operación
        balance_antes = config.balance_actual - ultima.beneficio
        print(f"   Balance antes de esta operación: \${balance_antes:.2f}")
        print(f"   Balance después: \${config.balance_actual:.2f}")

print(f"\n4. VERIFICACIÓN DE STOP LOSS:")
stop_loss_base = config.calcular_stop_loss(config.balance_stop_loss_base)
print(f"   Stop loss base: \${config.balance_stop_loss_base:.2f}")
print(f"   Stop loss esperado (2%): \${stop_loss_base:.2f}")
print(f"   Stop loss actual: \${config.stop_loss_actual:.2f}")
print(f"   Balance actual: \${config.balance_actual:.2f}")
print(f"   ¿Balance > Stop Loss? {config.balance_actual > config.stop_loss_actual}")

print(f"\n5. RECOMENDACIÓN:")
if config.estado == 'pausado' and config.balance_actual > config.stop_loss_actual:
    print("   ⚠️  El bot está pausado pero el balance está por encima del stop loss.")
    print("   Esto sugiere que la pausa NO fue causada por stop loss.")
    print("   Revisa los logs del sistema para encontrar la razón exacta.")
EOF
```

## Comandos Rápidos

```bash
# Ver estado rápido
python manage.py shell -c "from core.models import ConfiguracionBot; c=ConfiguracionBot.obtener(); print(f'Estado: {c.estado}, Pausado desde: {c.pausado_desde}, Balance: \${c.balance_actual:.2f}, Stop Loss: \${c.stop_loss_actual:.2f}')"

# Ver última operación
python manage.py shell -c "from historial.models import Operacion; op=Operacion.objetos.reales().order_by('-hora_inicio').first(); print(f'{op.hora_inicio} | {op.activo} {op.direccion} | {op.resultado} | \${op.beneficio:.2f}') if op else print('No hay operaciones')"

# Ver logs del momento de pausa
sudo journalctl -u binabot-loop.service --since "1 hour ago" --no-pager | grep -i "pausa\|pausado\|stop\|ganancia" | tail -20
```

