# Verificar WebSockets y Bases de Datos Separadas

## ✅ Confirmación: Bases de Datos Separadas

### Bot Principal
- **Modelo**: `historial.models.Operacion`
- **Configuración**: `core.models.ConfiguracionBot`
- **Base de datos**: Misma BD, pero tablas diferentes

### Bot Inverso
- **Modelo**: `trading_inverso.models.OperacionInversa`
- **Configuración**: `trading_inverso.models.ConfiguracionBotInverso`
- **Base de datos**: Misma BD, pero tablas diferentes

**✅ CONFIRMADO**: Cada bot tiene sus propias tablas y modelos completamente independientes.

---

## ✅ WebSockets Implementados

### Bot Principal
- **Consumer**: `integracion_deriv.consumers.DerivStatusConsumer`
- **Grupo**: `deriv_estado`
- **Routing**: `/ws/deriv/estado/`
- **Dashboard Consumer**: `dashboard.consumers.DashboardConsumer`
- **Grupo Dashboard**: `dashboard_updates`
- **Routing Dashboard**: `/ws/dashboard/`

### Bot Inverso
- **Consumer**: `trading_inverso.consumers.BotInversoConsumer` ✅ NUEVO
- **Grupo**: `deriv_estado_inverso` ✅ NUEVO
- **Routing**: `/ws/bot-inverso/` ✅ NUEVO
- **Servicio**: `trading_inverso.services_websocket.enviar_actualizacion_bot_inverso()` ✅ NUEVO

---

## Configuración en VPS

### 1. Hacer Pull

```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
git pull origin main
```

### 2. Reiniciar Servidor Web

```bash
sudo systemctl restart binabot.service
```

### 3. Crear Servicio para Actualizaciones WebSocket del Bot Inverso

Crear `/etc/systemd/system/binabot-inverso-websocket.service`:

```ini
[Unit]
Description=WebSocket Updates Bot Inverso
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/vitalmix.com.co/app/src
Environment="PATH=/var/www/vitalmix.com.co/app/.venv/bin"
ExecStart=/var/www/vitalmix.com.co/app/.venv/bin/python manage.py enviar_actualizaciones_bot_inverso --intervalo 10
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 4. Activar Servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable binabot-inverso-websocket.service
sudo systemctl start binabot-inverso-websocket.service
sudo systemctl status binabot-inverso-websocket.service
```

---

## Verificar que Funciona

### 1. Verificar WebSocket en el Navegador

Abre la consola del navegador (F12) en `/bot-inverso/` y deberías ver:

```
✅ Conectado al WebSocket del bot inverso
```

### 2. Verificar que Recibe Actualizaciones

En la consola deberías ver mensajes cada 10 segundos con datos del bot inverso.

### 3. Verificar Logs del Servicio

```bash
journalctl -u binabot-inverso-websocket.service -f
```

---

## Resumen de Separación

| Aspecto | Bot Principal | Bot Inverso |
|---------|---------------|-------------|
| **Modelo Operaciones** | `Operacion` | `OperacionInversa` |
| **Modelo Configuración** | `ConfiguracionBot` | `ConfiguracionBotInverso` |
| **Grupo WebSocket** | `deriv_estado` | `deriv_estado_inverso` |
| **Routing WebSocket** | `/ws/deriv/estado/` | `/ws/bot-inverso/` |
| **Consumer** | `DerivStatusConsumer` | `BotInversoConsumer` |
| **Servicio Actualizaciones** | `enviar_actualizacion_dashboard()` | `enviar_actualizacion_bot_inverso()` |
| **API Endpoints** | `/api/dashboard/*` | `/api/trading-inverso/*` |
| **Plantilla** | `templates/core/panel.html` | `templates/trading_inverso/dashboard.html` |

**✅ CONFIRMADO**: Todo está completamente separado e independiente.

