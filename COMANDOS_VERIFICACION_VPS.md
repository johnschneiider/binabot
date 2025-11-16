# Comandos para Verificar y Gestionar el Bot en la VPS

## 🔍 Verificación Rápida del Estado

### 1. Ver el estado de todos los servicios
```bash
systemctl status binabot-loop.service
systemctl status binabot-ticks.service
systemctl status binabot.service
```

### 2. Ver los últimos logs del bot principal
```bash
# Últimas 50 líneas
journalctl -u binabot-loop.service -n 50 --no-pager

# Últimas 100 líneas
journalctl -u binabot-loop.service -n 100 --no-pager

# Logs de las últimas 2 horas
journalctl -u binabot-loop.service --since "2 hours ago" --no-pager
```

### 3. Ver logs en tiempo real (seguimiento continuo)
```bash
journalctl -u binabot-loop.service -f
```

### 4. Ver solo errores recientes
```bash
journalctl -u binabot-loop.service --since "1 hour ago" --no-pager | grep -i error
```

### 5. Verificar procesos activos
```bash
ps aux | grep -E "(ejecutar_bot|recolectar_ticks|gunicorn)" | grep -v grep
```

## 🔄 Reiniciar Servicios

### Reiniciar el bot principal
```bash
sudo systemctl restart binabot-loop.service
```

### Reiniciar el recolector de ticks
```bash
sudo systemctl restart binabot-ticks.service
```

### Reiniciar el servidor web (Gunicorn)
```bash
sudo systemctl restart binabot.service
```

### Reiniciar todos los servicios
```bash
sudo systemctl restart binabot-loop.service binabot-ticks.service binabot.service
```

## 📊 Verificación Detallada

### Ver la configuración del servicio
```bash
systemctl cat binabot-loop.service
```

### Ver el directorio de trabajo y comando exacto
```bash
systemctl show binabot-loop.service | grep -E "(WorkingDirectory|ExecStart)"
```

### Ver logs del recolector de ticks
```bash
journalctl -u binabot-ticks.service -n 50 --no-pager
```

### Ver logs del servidor web
```bash
journalctl -u binabot.service -n 50 --no-pager
```

## 🐛 Diagnóstico de Problemas

### Ver si hay errores de Python
```bash
journalctl -u binabot-loop.service -n 200 --no-pager | grep -E "(Error|Exception|Traceback)"
```

### Ver si hay problemas de conexión a la base de datos
```bash
journalctl -u binabot-loop.service -n 200 --no-pager | grep -i "database\|postgres\|connection"
```

### Ver si hay problemas con la API de Deriv
```bash
journalctl -u binabot-loop.service -n 200 --no-pager | grep -i "deriv\|api\|token"
```

### Verificar que el bot está en pausa y por qué
```bash
# Conectarse a Django shell
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate
python manage.py shell

# En el shell de Django:
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
print(f"Estado: {config.estado}")
print(f"Pausado desde: {config.pausado_desde}")
print(f"Pausa finaliza: {config.pausa_finaliza}")
print(f"Mejor horario: {config.mejor_horario}")
print(f"Última simulación: {config.ultima_simulacion}")
```

## 🔧 Comandos Útiles Adicionales

### Ver cuánto tiempo lleva corriendo el servicio
```bash
systemctl status binabot-loop.service | grep "Active:"
```

### Ver el uso de recursos
```bash
ps aux | grep ejecutar_bot | grep -v grep
```

### Verificar que los servicios están habilitados para iniciar al arrancar
```bash
systemctl is-enabled binabot-loop.service
systemctl is-enabled binabot-ticks.service
systemctl is-enabled binabot.service
```

### Habilitar servicios para inicio automático (si no están habilitados)
```bash
sudo systemctl enable binabot-loop.service
sudo systemctl enable binabot-ticks.service
sudo systemctl enable binabot.service
```

## 📝 Script de Verificación Completa

Puedes usar el script `verificar_bot_vps.sh` que crea un resumen completo:

```bash
chmod +x verificar_bot_vps.sh
./verificar_bot_vps.sh
```

## ⚠️ Si el Bot Está Pausado

Si el bot está en pausa y quieres verificar por qué:

1. **Ver el estado en la base de datos:**
```bash
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate
python manage.py shell -c "from core.models import ConfiguracionBot; c = ConfiguracionBot.obtener(); print(f'Estado: {c.estado}, Pausado desde: {c.pausado_desde}, Finaliza: {c.pausa_finaliza}')"
```

2. **Ver si hay simulaciones ejecutándose:**
```bash
journalctl -u binabot-loop.service -n 100 --no-pager | grep -i "simulación\|simulation"
```

3. **Verificar que el recolector de ticks está funcionando:**
```bash
journalctl -u binabot-ticks.service -n 50 --no-pager | tail -20
```

