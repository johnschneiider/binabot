# Configuración del Bot Inverso

Este documento explica cómo configurar y ejecutar el bot inverso que ejecuta la estrategia opuesta al bot principal.

## ¿Qué es el Bot Inverso?

El bot inverso monitorea las operaciones del bot principal y ejecuta automáticamente la dirección opuesta:
- Si el bot principal hace **CALL** → El bot inverso hace **PUT**
- Si el bot principal hace **PUT** → El bot inverso hace **CALL**

Esto permite:
- Diversificar riesgo
- Aprovechar ambas direcciones del mercado
- Comparar desempeño de ambas estrategias

## Estructura

- **Base de datos separada**: El bot inverso tiene sus propios modelos (`OperacionInversa`, `ConfiguracionBotInverso`)
- **Balance independiente**: Cada bot maneja su propio balance y stop loss
- **Plantillas separadas**: Cada bot tiene su propio dashboard

## Pasos de Configuración

### 1. Hacer Migraciones

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
python manage.py makemigrations trading_inverso
python manage.py migrate trading_inverso
```

### 2. Inicializar Balance del Bot Inverso

```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
config.balance_actual = 100.00  # Ajusta el balance inicial
config.save()
print(f'Balance inicial del bot inverso: ${config.balance_actual}')
"
```

### 3. Crear Servicio Systemd

Crear el archivo `/etc/systemd/system/binabot-inverso.service`:

```ini
[Unit]
Description=Bot Inverso - Ejecuta estrategia opuesta al bot principal
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/vitalmix.com.co/app/src
Environment="PATH=/var/www/vitalmix.com.co/app/.venv/bin"
ExecStart=/var/www/vitalmix.com.co/app/.venv/bin/python manage.py ejecutar_bot_inverso --intervalo 5
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 4. Activar y Iniciar el Servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable binabot-inverso.service
sudo systemctl start binabot-inverso.service
sudo systemctl status binabot-inverso.service
```

### 5. Ver Logs

```bash
# Ver logs en tiempo real
journalctl -u binabot-inverso.service -f

# Ver últimos logs
journalctl -u binabot-inverso.service --since "10 minutes ago" --no-pager
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

### Ver Estado

```bash
sudo systemctl status binabot-inverso.service
```

### Reanudar Bot Inverso (si está pausado)

```bash
python manage.py shell -c "
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.configuracion.reanudar()
print('Bot inverso reanudado')
"
```

## Cómo Funciona

1. **Monitoreo**: El bot inverso verifica cada 5 segundos si hay nuevas operaciones del bot principal
2. **Detección**: Cuando detecta una nueva operación del bot principal (que no sea simulada y esté completada)
3. **Inversión**: Ejecuta la dirección opuesta en el mismo activo
4. **Registro**: Guarda la operación en su propia base de datos con referencia a la operación principal

## URLs Disponibles

- **Home**: `/` - Muestra ambos bots
- **Bot Principal**: `/bot-principal/` - Dashboard del bot principal
- **Bot Inverso**: `/bot-inverso/` - Dashboard del bot inverso
- **API Estado Inverso**: `/api/trading-inverso/estado/`
- **API Históricos Inverso**: `/api/trading-inverso/historicos/`

## Notas Importantes

1. **Balance Separado**: Cada bot tiene su propio balance. Asegúrate de inicializar el balance del bot inverso antes de activarlo.

2. **Stop Loss Independiente**: Cada bot calcula su propio stop loss basado en su balance.

3. **Pausa Automática**: Si el bot inverso alcanza su stop loss, se pausa automáticamente por 24 horas.

4. **Sincronización**: El bot inverso sincroniza su balance desde la API de Deriv periódicamente.

5. **Operaciones Simultáneas**: Ambos bots pueden ejecutarse simultáneamente sin interferir entre sí.

## Solución de Problemas

### El bot inverso no ejecuta operaciones

1. Verificar que el bot principal esté ejecutando operaciones:
```bash
python manage.py shell -c "
from historial.models import Operacion
ops = Operacion.objetos.reales().order_by('-hora_inicio')[:5]
for op in ops:
    print(f'{op.activo} {op.direccion} - {op.resultado}')
"
```

2. Verificar estado del bot inverso:
```bash
python manage.py shell -c "
from trading_inverso.models import ConfiguracionBotInverso
config = ConfiguracionBotInverso.obtener()
print(f'Estado: {config.estado}')
print(f'Balance: {config.balance_actual}')
print(f'En operación: {config.en_operacion}')
"
```

3. Ver logs del bot inverso:
```bash
journalctl -u binabot-inverso.service -f
```

### El bot inverso está pausado

Si el bot inverso alcanzó su stop loss, se pausa automáticamente. Para reanudarlo:

```bash
python manage.py shell -c "
from trading_inverso.services import GestorBotInverso
gestor = GestorBotInverso()
gestor.configuracion.reanudar()
print('Bot inverso reanudado')
"
```

## Comparación de Desempeño

Para comparar el desempeño de ambos bots:

```bash
# Bot Principal
python manage.py estadisticas_bot

# Bot Inverso (crear comando similar si es necesario)
python manage.py shell -c "
from trading_inverso.models import OperacionInversa
ops = OperacionInversa.objetos.reales()
total = ops.count()
ganadas = ops.filter(resultado='win').count()
winrate = (ganadas / total * 100) if total > 0 else 0
beneficio = sum(float(op.beneficio) for op in ops)
print(f'Bot Inverso: {total} ops | {ganadas}G | Winrate: {winrate:.1f}% | Beneficio: ${beneficio:.2f}')
"
```

