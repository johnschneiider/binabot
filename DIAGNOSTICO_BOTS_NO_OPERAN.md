# Diagnóstico: Ningún Bot Está Operando

## Comandos de Diagnóstico

### 1. Verificar Estado de los Bots

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate

# Estado del bot principal
python manage.py shell -c "
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
print('BOT PRINCIPAL:')
print(f'  Estado: {config.estado}')
print(f'  Balance: \${config.balance_actual}')
print(f'  Stop Loss: \${config.stop_loss_actual}')
print(f'  En operación: {config.en_operacion}')
print(f'  Pausado desde: {config.pausado_desde}')
print(f'  Pausa finaliza: {config.pausa_finaliza}')
"

# Estado del bot inverso
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
print('BOT INVERSO:')
print(f'  Estado: {config.estado}')
print(f'  Balance: \${config.balance_actual}')
print(f'  Stop Loss: \${config.stop_loss_actual}')
print(f'  En operación: {config.en_operacion}')
print(f'  Pausado desde: {config.pausado_desde}')
print(f'  Pausa finaliza: {config.pausa_finaliza}')
"
```

### 2. Verificar Servicios Systemd

```bash
# Ver estado de todos los servicios
sudo systemctl status binabot.service binabot-loop.service binabot-ticks.service binabot-inverso.service

# Ver si están corriendo
sudo systemctl is-active binabot-loop.service
sudo systemctl is-active binabot-ticks.service
sudo systemctl is-active binabot-inverso.service

# Ver logs recientes
sudo journalctl -u binabot-loop.service --since "10 minutes ago" --no-pager | tail -50
sudo journalctl -u binabot-inverso.service --since "10 minutes ago" --no-pager | tail -50
```

### 3. Verificar Procesos Python

```bash
# Ver procesos del bot
ps aux | grep -E "(ejecutar_bot|ejecutar_bot_inverso|recolectar_ticks)" | grep -v grep

# Ver procesos de Python relacionados
ps aux | grep python | grep -E "(manage.py|binabot)" | grep -v grep
```

### 4. Verificar Últimas Operaciones

```bash
python manage.py shell -c "
from historial.models import Operacion
from trading_inverso.models import OperacionInversa
from django.utils import timezone
from datetime import timedelta

# Última operación principal
ultima_principal = Operacion.objetos.reales().order_by('-hora_inicio').first()
if ultima_principal:
    print(f'Última operación principal: {ultima_principal.hora_inicio} ({ultima_principal.activo} {ultima_principal.direccion})')
    tiempo_desde = timezone.now() - ultima_principal.hora_inicio
    print(f'Hace: {tiempo_desde}')
else:
    print('No hay operaciones del bot principal')

# Última operación inversa
ultima_inversa = OperacionInversa.objects.filter(simulada=False).order_by('-hora_inicio').first()
if ultima_inversa:
    print(f'Última operación inversa: {ultima_inversa.hora_inicio} ({ultima_inversa.activo} {ultima_inversa.direccion})')
    tiempo_desde = timezone.now() - ultima_inversa.hora_inicio
    print(f'Hace: {tiempo_desde}')
else:
    print('No hay operaciones del bot inverso')
"
```

### 5. Verificar Activos Permitidos

```bash
python manage.py shell -c "
from core.models import ActivoPermitido
activos = ActivoPermitido.objects.filter(activo=True)
print(f'Activos permitidos: {activos.count()}')
for a in activos:
    print(f'  - {a.nombre}')
"
```

### 6. Verificar Balance y Stop Loss

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
from trading_inverso.models import ConfiguracionBotInverso
from integracion_deriv.client import obtener_balance_sync

# Balance real de Deriv
try:
    respuesta = obtener_balance_sync()
    balance_info = respuesta.get('balance', {})
    balance_deriv = balance_info.get('balance', 0)
    print(f'Balance en Deriv: \${balance_deriv}')
except Exception as e:
    print(f'Error obteniendo balance: {e}')

# Bot principal
config_principal = ConfiguracionBot.obtener()
print(f'Bot Principal - Balance: \${config_principal.balance_actual}, Stop Loss: \${config_principal.stop_loss_actual}')
print(f'  ¿Puede operar? {config_principal.balance_actual > config_principal.stop_loss_actual}')

# Bot inverso
config_inverso = ConfiguracionBotInverso.obtener()
print(f'Bot Inverso - Balance: \${config_inverso.balance_actual}, Stop Loss: \${config_inverso.stop_loss_actual}')
print(f'  ¿Puede operar? {config_inverso.balance_actual > config_inverso.stop_loss_actual}')
"
```

### 7. Verificar Logs del Motor de Trading

```bash
# Ver logs del comando ejecutar_bot
sudo journalctl -u binabot-loop.service --since "30 minutes ago" --no-pager | grep -E "(ejecutar_ciclo|operacion|ERROR|WARNING)" | tail -50

# Ver logs del bot inverso
sudo journalctl -u binabot-inverso.service --since "30 minutes ago" --no-pager | grep -E "(ciclo|operacion|ERROR|WARNING)" | tail -50
```

### 8. Probar Ejecución Manual

```bash
# Ejecutar un ciclo manualmente del bot principal
python manage.py shell -c "
from trading.services_profesional import MotorTradingProfesional
from core.services import GestorBotCore

gestor = GestorBotCore()
motor = MotorTradingProfesional(gestor)
print('Ejecutando ciclo manual...')
operacion = motor.ejecutar_ciclo()
if operacion:
    print(f'Operación creada: {operacion.id} - {operacion.activo} {operacion.direccion}')
else:
    print('No se creó operación')
    if hasattr(motor, 'ultimo_mensaje_diagnostico'):
        print(f'Razón: {motor.ultimo_mensaje_diagnostico}')
"
```

## Soluciones Comunes

### Problema 1: Bots Pausados

```bash
# Reanudar bot principal
python manage.py shell -c "
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
config.reanudar()
print('Bot principal reanudado')
"

# Reanudar bot inverso
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
config.reanudar()
print('Bot inverso reanudado')
"
```

### Problema 2: Servicios No Corriendo

```bash
# Iniciar servicios
sudo systemctl start binabot-loop.service
sudo systemctl start binabot-ticks.service
sudo systemctl start binabot-inverso.service

# Verificar que estén activos
sudo systemctl status binabot-loop.service binabot-ticks.service binabot-inverso.service
```

### Problema 3: Balance Bajo Stop Loss

```bash
# Sincronizar balance desde Deriv
python manage.py shell -c "
from core.services import GestorBotCore
from trading_inverso.services import GestorBotInverso

gestor_principal = GestorBotCore()
gestor_principal.sincronizar_balance_desde_api()

gestor_inverso = GestorBotInverso()
gestor_inverso.sincronizar_balance_desde_api()

print('Balances sincronizados')
"
```

### Problema 4: No Hay Activos Permitidos

```bash
# Verificar y activar activos
python manage.py shell -c "
from core.models import ActivoPermitido
activos = ['R_10', 'R_25', 'R_50', 'R_100', 'JD100', 'RDBEAR']
for nombre in activos:
    activo, creado = ActivoPermitido.objects.get_or_create(nombre=nombre)
    activo.activo = True
    activo.save()
    print(f'Activo {nombre} activado')
"
```

## Verificar Configuración Completa

```bash
python manage.py shell << EOF
from core.models import ConfiguracionBot, ActivoPermitido
from trading_inverso.models import ConfiguracionBotInverso
from integracion_deriv.client import obtener_balance_sync

print("=== DIAGNÓSTICO COMPLETO ===\n")

# 1. Balance Deriv
try:
    respuesta = obtener_balance_sync()
    balance_deriv = respuesta.get('balance', {}).get('balance', 0)
    print(f"✅ Balance Deriv: \${balance_deriv}")
except Exception as e:
    print(f"❌ Error obteniendo balance Deriv: {e}")

# 2. Bot Principal
config_principal = ConfiguracionBot.obtener()
print(f"\n🤖 BOT PRINCIPAL:")
print(f"   Estado: {config_principal.estado}")
print(f"   Balance: \${config_principal.balance_actual}")
print(f"   Stop Loss: \${config_principal.stop_loss_actual}")
print(f"   En operación: {config_principal.en_operacion}")
print(f"   Puede operar: {config_principal.estado == 'operando' and config_principal.balance_actual > config_principal.stop_loss_actual}")

# 3. Bot Inverso
config_inverso = ConfiguracionBotInverso.obtener()
print(f"\n🔄 BOT INVERSO:")
print(f"   Estado: {config_inverso.estado}")
print(f"   Balance: \${config_inverso.balance_actual}")
print(f"   Stop Loss: \${config_inverso.stop_loss_actual}")
print(f"   En operación: {config_inverso.en_operacion}")
print(f"   Puede operar: {config_inverso.estado == 'operando' and config_inverso.balance_actual > config_inverso.stop_loss_actual}")

# 4. Activos
activos = ActivoPermitido.objects.filter(activo=True)
print(f"\n📊 ACTIVOS PERMITIDOS: {activos.count()}")
for a in activos[:10]:
    print(f"   - {a.nombre}")

print("\n=== FIN DIAGNÓSTICO ===")
EOF
```

