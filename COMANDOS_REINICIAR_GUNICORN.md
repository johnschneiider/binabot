# Cómo Reiniciar Gunicorn

## Método 1: Reiniciar el Servicio Systemd (Recomendado)

El proyecto usa el servicio `binabot.service` que incluye Gunicorn:

```bash
# Reiniciar el servicio completo (incluye Gunicorn)
sudo systemctl restart binabot.service

# Verificar el estado
sudo systemctl status binabot.service

# Ver logs en tiempo real
sudo journalctl -u binabot.service -f
```

## Método 2: Si Existe un Servicio Separado de Gunicorn

Si Gunicorn está en un servicio separado:

```bash
# Reiniciar Gunicorn
sudo systemctl restart gunicorn

# O si está en otro nombre
sudo systemctl restart gunicorn.service

# Verificar estado
sudo systemctl status gunicorn
```

## Método 3: Reiniciar por Señal (Sin Detener)

Si quieres reiniciar sin perder conexiones activas:

```bash
# Encontrar el proceso de Gunicorn
ps aux | grep gunicorn

# Enviar señal HUP para recargar configuración
sudo kill -HUP $(pgrep -f gunicorn)

# O si conoces el PID
sudo kill -HUP <PID>
```

## Método 4: Reiniciar Todos los Servicios Relacionados

```bash
# Reiniciar todos los servicios del bot
sudo systemctl restart binabot.service binabot-loop.service binabot-ticks.service

# Si existe el servicio del dashboard
sudo systemctl restart binabot-dashboard.service
```

## Verificar que Gunicorn Está Corriendo

```bash
# Ver procesos de Gunicorn
ps aux | grep gunicorn | grep -v grep

# Ver puertos en uso
sudo netstat -tlnp | grep gunicorn
# O con ss
sudo ss -tlnp | grep gunicorn

# Verificar logs
sudo journalctl -u binabot.service -n 50 --no-pager
```

## Comandos Útiles

```bash
# Ver todos los servicios relacionados
sudo systemctl list-units | grep -E "binabot|gunicorn|django"

# Verificar si el servicio está habilitado
sudo systemctl is-enabled binabot.service

# Habilitar el servicio para que inicie automáticamente
sudo systemctl enable binabot.service

# Ver logs de errores recientes
sudo journalctl -u binabot.service --since "10 minutes ago" --no-pager | grep -i error
```

## Después de Reiniciar

1. **Verificar que el servicio está activo**:
   ```bash
   sudo systemctl status binabot.service
   ```

2. **Verificar que la aplicación responde**:
   ```bash
   curl http://localhost:8000/  # O el puerto que uses
   ```

3. **Verificar logs**:
   ```bash
   sudo journalctl -u binabot.service -f
   ```

## Solución de Problemas

### Si el servicio no inicia:
```bash
# Ver errores detallados
sudo journalctl -u binabot.service -n 100 --no-pager

# Verificar la configuración del servicio
sudo systemctl cat binabot.service
```

### Si Gunicorn no responde:
```bash
# Matar procesos zombie
sudo pkill -9 gunicorn

# Reiniciar el servicio
sudo systemctl restart binabot.service
```

