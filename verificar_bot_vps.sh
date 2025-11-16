#!/bin/bash
# Script para verificar el estado y logs del bot en la VPS

echo "=========================================="
echo "VERIFICACIÓN DEL ESTADO DEL BOT"
echo "=========================================="
echo ""

echo "1. ESTADO DE LOS SERVICIOS:"
echo "----------------------------------------"
systemctl status binabot-loop.service --no-pager -l
echo ""
systemctl status binabot-ticks.service --no-pager -l
echo ""
systemctl status binabot.service --no-pager -l
echo ""

echo "2. ÚLTIMOS 50 LOGS DEL BOT PRINCIPAL:"
echo "----------------------------------------"
journalctl -u binabot-loop.service -n 50 --no-pager
echo ""

echo "3. ÚLTIMOS 30 LOGS DEL RECOLECTOR DE TICKS:"
echo "----------------------------------------"
journalctl -u binabot-ticks.service -n 30 --no-pager
echo ""

echo "4. ERRORES RECIENTES (últimas 2 horas):"
echo "----------------------------------------"
journalctl -u binabot-loop.service --since "2 hours ago" --no-pager | grep -i error || echo "No se encontraron errores recientes"
echo ""

echo "5. VERIFICAR SI LOS PROCESOS ESTÁN CORRIENDO:"
echo "----------------------------------------"
ps aux | grep -E "(ejecutar_bot|recolectar_ticks|gunicorn)" | grep -v grep || echo "No se encontraron procesos activos"
echo ""

echo "6. CONFIGURACIÓN DEL SERVICIO PRINCIPAL:"
echo "----------------------------------------"
systemctl cat binabot-loop.service | grep -E "(ExecStart|WorkingDirectory|User)" || echo "No se pudo leer la configuración"
echo ""

echo "=========================================="
echo "FIN DE LA VERIFICACIÓN"
echo "=========================================="
echo ""
echo "Para ver logs en tiempo real, ejecuta:"
echo "  journalctl -u binabot-loop.service -f"
echo ""
echo "Para reiniciar el bot, ejecuta:"
echo "  sudo systemctl restart binabot-loop.service"
echo "  sudo systemctl restart binabot-ticks.service"

