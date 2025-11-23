# Verificar y Corregir URLs del Bot Inverso

## Problema: Error 404 al acceder a `/bot-inverso/`

## Solución: Reiniciar el Servidor Web

### 1. Verificar que las URLs están correctas

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
python manage.py shell -c "
from django.urls import reverse
try:
    url = reverse('trading_inverso:dashboard')
    print(f'URL encontrada: {url}')
except Exception as e:
    print(f'Error: {e}')
"
```

### 2. Reiniciar el Servidor Web (Gunicorn/uWSGI)

```bash
# Si usas Gunicorn con systemd
sudo systemctl restart gunicorn
# O
sudo systemctl restart binabot-dashboard.service

# Si usas uWSGI
sudo systemctl restart uwsgi

# Si usas supervisor
sudo supervisorctl restart all

# Verificar qué servicio está corriendo
sudo systemctl list-units | grep -E "gunicorn|uwsgi|binabot|django"
```

### 3. Verificar que el servidor está corriendo

```bash
# Ver procesos de Python/Django
ps aux | grep -E "gunicorn|uwsgi|manage.py|runserver"

# Ver logs del servidor web
sudo journalctl -u gunicorn -f
# O
sudo journalctl -u binabot-dashboard -f
```

### 4. Verificar configuración de Nginx (si aplica)

```bash
# Verificar configuración de Nginx
sudo nginx -t

# Reiniciar Nginx si es necesario
sudo systemctl restart nginx
```

### 5. Verificar que las plantillas existen

```bash
ls -la /var/www/vitalmix.com.co/app/src/templates/trading_inverso/dashboard.html
ls -la /var/www/vitalmix.com.co/app/src/templates/home.html
```

### 6. Verificar que la app está en INSTALLED_APPS

```bash
python manage.py shell -c "
from django.conf import settings
if 'trading_inverso' in settings.INSTALLED_APPS:
    print('✅ trading_inverso está en INSTALLED_APPS')
else:
    print('❌ trading_inverso NO está en INSTALLED_APPS')
"
```

## URLs Correctas

Después de reiniciar, estas URLs deberían funcionar:

- **Home**: `https://vitalmix.com.co/`
- **Bot Principal**: `https://vitalmix.com.co/bot-principal/`
- **Bot Inverso**: `https://vitalmix.com.co/bot-inverso/`

## Si el problema persiste

### Verificar logs de Django

```bash
# Ver logs de errores
tail -f /var/log/django/error.log
# O donde estén los logs de tu aplicación
```

### Probar directamente con runserver (solo para debug)

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
python manage.py runserver 0.0.0.0:8000
# Luego acceder a http://vitalmix.com.co:8000/bot-inverso/
```

### Verificar permisos de archivos

```bash
# Verificar permisos de plantillas
ls -la templates/trading_inverso/
ls -la templates/home.html

# Si es necesario, corregir permisos
chmod 644 templates/trading_inverso/dashboard.html
chmod 644 templates/home.html
```

