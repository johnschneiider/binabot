# Verificar y Activar Servicios de los Bots

## Comandos para Verificar Servicios

```bash
# 1. Ver estado de todos los servicios
sudo systemctl status binabot-loop.service binabot-ticks.service binabot-inverso.service

# 2. Ver si están activos
sudo systemctl is-active binabot-loop.service
sudo systemctl is-active binabot-ticks.service
sudo systemctl is-active binabot-inverso.service

# 3. Ver si están habilitados (para iniciar automáticamente)
sudo systemctl is-enabled binabot-loop.service
sudo systemctl is-enabled binabot-ticks.service
sudo systemctl is-enabled binabot-inverso.service

# 4. Ver logs recientes
sudo journalctl -u binabot-loop.service --since "10 minutes ago" --no-pager | tail -50
sudo journalctl -u binabot-ticks.service --since "10 minutes ago" --no-pager | tail -50
sudo journalctl -u binabot-inverso.service --since "10 minutes ago" --no-pager | tail -50
```

## Si los Servicios NO Están Corriendo

```bash
# Iniciar servicios
sudo systemctl start binabot-loop.service
sudo systemctl start binabot-ticks.service
sudo systemctl start binabot-inverso.service

# Habilitar para que inicien automáticamente al reiniciar
sudo systemctl enable binabot-loop.service
sudo systemctl enable binabot-ticks.service
sudo systemctl enable binabot-inverso.service

# Verificar que estén corriendo
sudo systemctl status binabot-loop.service binabot-ticks.service binabot-inverso.service
```

## Si los Servicios Están Corriendo pero No Operan

```bash
# Ver logs detallados
sudo journalctl -u binabot-loop.service -f

# Ver errores
sudo journalctl -u binabot-loop.service --since "1 hour ago" --no-pager | grep -i error

# Reiniciar servicios
sudo systemctl restart binabot-loop.service
sudo systemctl restart binabot-ticks.service
sudo systemctl restart binabot-inverso.service
```

## Verificar Procesos Python

```bash
# Ver procesos del bot
ps aux | grep -E "(ejecutar_bot|ejecutar_bot_inverso|recolectar_ticks)" | grep -v grep

# Ver todos los procesos Python relacionados
ps aux | grep python | grep -E "(manage.py|binabot)" | grep -v grep
```

## Comando Completo de Verificación

```bash
#!/bin/bash
echo "=== VERIFICACIÓN DE SERVICIOS ==="
echo ""

echo "1. Estado de servicios:"
sudo systemctl status binabot-loop.service --no-pager -l | head -10
echo ""
sudo systemctl status binabot-ticks.service --no-pager -l | head -10
echo ""
sudo systemctl status binabot-inverso.service --no-pager -l | head -10
echo ""

echo "2. Procesos Python:"
ps aux | grep -E "(ejecutar_bot|ejecutar_bot_inverso|recolectar_ticks)" | grep -v grep || echo "No se encontraron procesos"
echo ""

echo "3. Últimos logs del bot principal:"
sudo journalctl -u binabot-loop.service --since "5 minutes ago" --no-pager | tail -20
```

