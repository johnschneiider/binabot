# Actualizaciones en Tiempo Real del Dashboard

## Resumen

Se ha implementado un sistema de actualizaciones en tiempo real para el dashboard que actualiza la página cada 10 segundos automáticamente sin necesidad de recargar.

## Componentes Implementados

### 1. WebSocket Consumer (`dashboard/consumers.py`)
- Maneja las conexiones WebSocket del dashboard
- Envía actualizaciones a todos los clientes conectados

### 2. Servicio de Actualizaciones (`dashboard/services.py`)
- Recolecta todos los datos del dashboard
- Envía actualizaciones a través del canal WebSocket

### 3. Comando de Envío (`dashboard/management/commands/enviar_actualizaciones_dashboard.py`)
- Envía actualizaciones cada 10 segundos
- Debe ejecutarse como servicio systemd

### 4. JavaScript (`static/js/panel.js`)
- Se conecta al WebSocket del dashboard
- Recibe y procesa actualizaciones automáticamente
- Actualiza la página sin recargar

## Configuración

### 1. Actualizar ASGI (ya hecho)
El archivo `bot_deriv/asgi.py` ya incluye las rutas del dashboard.

### 2. Crear Servicio Systemd

Crear el archivo `/etc/systemd/system/binabot-dashboard.service`:

```ini
[Unit]
Description=Enviador de actualizaciones del dashboard binabot
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/vitalmix.com.co/app/src
Environment="PATH=/var/www/vitalmix.com.co/app/.venv/bin"
ExecStart=/var/www/vitalmix.com.co/app/.venv/bin/python manage.py enviar_actualizaciones_dashboard --intervalo 10
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. Activar el Servicio

```bash
# Recargar systemd
systemctl daemon-reload

# Habilitar el servicio
systemctl enable binabot-dashboard.service

# Iniciar el servicio
systemctl start binabot-dashboard.service

# Verificar estado
systemctl status binabot-dashboard.service

# Ver logs
journalctl -u binabot-dashboard.service -f
```

## Funcionamiento

1. **Servidor**: El comando `enviar_actualizaciones_dashboard` se ejecuta cada 10 segundos y envía datos actualizados a través de WebSocket.

2. **Cliente**: El JavaScript se conecta al WebSocket `/ws/dashboard/` y recibe actualizaciones automáticamente.

3. **Actualización**: Cuando se recibe una actualización, el JavaScript actualiza todos los elementos de la página sin recargar.

## Datos que se Actualizan

- Estado del bot (operando/pausado)
- Balance actual, meta y stop loss
- Winrate y estadísticas
- Últimas operaciones
- Temporizador de pausa
- Ganancia/pérdida acumulada

## Verificación

1. Abrir la consola del navegador (F12)
2. Deberías ver: `[Dashboard] Conectado al canal de actualizaciones en tiempo real.`
3. Cada 10 segundos deberías ver: `[Dashboard] Actualización recibida: [timestamp]`
4. Los valores en la página deberían actualizarse automáticamente

## Solución de Problemas

### El WebSocket no se conecta
- Verificar que el servidor ASGI esté corriendo (Daphne o similar)
- Verificar que el puerto WebSocket esté abierto
- Revisar logs del servidor

### No se reciben actualizaciones
- Verificar que el servicio `binabot-dashboard.service` esté corriendo
- Revisar logs: `journalctl -u binabot-dashboard.service -f`
- Verificar que Channels esté configurado correctamente

### Actualizaciones lentas
- Verificar la carga del servidor
- Ajustar el intervalo en el servicio systemd (cambiar `--intervalo 10` a otro valor)

