# Comandos para Verificar Estado de Django en VPS

## 1. Verificar Estado del Servicio Systemd

```bash
cd /var/www/vitalmix.com.co/app
source .venv/bin/activate

# Estado del servicio
systemctl status binabot-vitalmix.service --no-pager -l

# Ver si está corriendo
systemctl is-active binabot-vitalmix.service

# Ver si está habilitado
systemctl is-enabled binabot-vitalmix.service
```

## 2. Ver Logs del Servicio (Últimos Errores)

```bash
# Últimos 100 líneas de logs
journalctl -u binabot-vitalmix.service -n 100 --no-pager

# Logs en tiempo real (Ctrl+C para salir)
journalctl -u binabot-vitalmix.service -f

# Solo errores y warnings
journalctl -u binabot-vitalmix.service --no-pager | grep -i "error\|exception\|traceback\|connection\|timeout\|failed"
```

## 3. Verificar Errores de Conexión a Base de Datos

```bash
cd /var/www/vitalmix.com.co/app
source .venv/bin/activate

# Probar conexión a la base de datos
python manage.py shell -c "from django.db import connection; cursor = connection.cursor(); cursor.execute('SELECT 1'); print('BD OK:', cursor.fetchone())"

# Verificar migraciones pendientes
python manage.py showmigrations

# Verificar estado de la base de datos
python manage.py check --database default
```

## 4. Verificar Errores de Conexión a API Deriv

```bash
cd /var/www/vitalmix.com.co/app
source .venv/bin/activate

# Ver logs específicos de conexión Deriv
journalctl -u binabot-vitalmix.service --no-pager | grep -i "deriv\|websocket\|api\|connection\|timeout" | tail -50

# Verificar si hay errores de autenticación
journalctl -u binabot-vitalmix.service --no-pager | grep -i "auth\|token\|unauthorized\|forbidden" | tail -20
```

## 5. Verificar Procesos Python Corriendo

```bash
# Ver todos los procesos Python relacionados
ps aux | grep python | grep -v grep

# Ver procesos específicos del bot
ps aux | grep "deriv_stream\|manage.py" | grep -v grep

# Ver uso de recursos
top -p $(pgrep -f "deriv_stream\|manage.py" | tr '\n' ',' | sed 's/,$//')
```

## 6. Verificar Logs de Django (si hay archivos de log)

```bash
cd /var/www/vitalmix.com.co/app

# Buscar archivos de log
find . -name "*.log" -type f

# Ver últimos errores en logs (si existen)
tail -100 logs/*.log 2>/dev/null || echo "No hay archivos de log"
```

## 7. Verificar Errores de Conexión WebSocket

```bash
# Buscar errores de WebSocket en logs
journalctl -u binabot-vitalmix.service --no-pager | grep -i "websocket\|ws\|socket\|disconnect\|reconnect" | tail -50
```

## 8. Comando Completo de Diagnóstico

```bash
cd /var/www/vitalmix.com.co/app && source .venv/bin/activate && \
echo "===== ESTADO SERVICIO =====" && \
systemctl status binabot-vitalmix.service --no-pager -l | head -20 && \
echo && \
echo "===== ÚLTIMOS ERRORES (últimas 50 líneas) =====" && \
journalctl -u binabot-vitalmix.service -n 50 --no-pager | grep -i "error\|exception\|traceback\|connection\|timeout\|failed" && \
echo && \
echo "===== ERRORES DERIV/WEBSOCKET (últimas 30 líneas) =====" && \
journalctl -u binabot-vitalmix.service --no-pager | grep -i "deriv\|websocket\|ws\|api\|connection\|timeout" | tail -30 && \
echo && \
echo "===== PROCESOS PYTHON =====" && \
ps aux | grep python | grep -v grep && \
echo && \
echo "===== PRUEBA CONEXIÓN BD =====" && \
python manage.py dbshell --command "SELECT 1;" 2>&1
```

## 9. Verificar si el Bot Está Recibiendo Ticks

```bash
cd /var/www/vitalmix.com.co/app
source .venv/bin/activate

# Verificar últimos ticks guardados
python manage.py shell -c "
from gestion_riesgo.models import TickDerivSnapshot, Cuenta
from django.utils import timezone
from datetime import timedelta

# Verificar ticks de R_10
cuenta_r10 = Cuenta.objects.filter(simbolo='R_10').first()
if cuenta_r10:
    ticks_r10 = TickDerivSnapshot.objects.filter(cuenta=cuenta_r10).order_by('-epoch')[:5]
    print('R_10 - Últimos 5 ticks:')
    for t in ticks_r10:
        print(f'  Epoch: {t.epoch}, Precio: {t.precio}, Created: {t.created_at}')
    print(f'Total ticks R_10: {TickDerivSnapshot.objects.filter(cuenta=cuenta_r10).count()}')
else:
    print('No hay cuenta R_10')

# Verificar ticks de R_100
cuenta_r100 = Cuenta.objects.filter(simbolo='R_100').first()
if cuenta_r100:
    ticks_r100 = TickDerivSnapshot.objects.filter(cuenta=cuenta_r100).order_by('-epoch')[:5]
    print('R_100 - Últimos 5 ticks:')
    for t in ticks_r100:
        print(f'  Epoch: {t.epoch}, Precio: {t.precio}, Created: {t.created_at}')
    print(f'Total ticks R_100: {TickDerivSnapshot.objects.filter(cuenta=cuenta_r100).count()}')
else:
    print('No hay cuenta R_100')
"
```

## 10. Reiniciar el Servicio (si es necesario)

```bash
# Reiniciar el servicio
sudo systemctl restart binabot-vitalmix.service

# Ver estado después de reiniciar
systemctl status binabot-vitalmix.service --no-pager -l

# Ver logs después del reinicio
journalctl -u binabot-vitalmix.service -n 50 --no-pager
```
