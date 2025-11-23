# Pull Seguro Sin Afectar Bot en Ejecución

## ⚠️ IMPORTANTE: El bot en ejecución NO se afecta hasta que reinicies el servicio

Cuando haces `git pull`, solo actualizas los archivos en disco. El bot que está corriendo en memoria **NO se afecta** hasta que reinicies el servicio.

## Pasos Seguros

### 1. Hacer Pull (NO afecta el bot en ejecución)
```bash
cd /var/www/vitalmix.com.co/app/src
source ../.venv/bin/activate
git pull origin main
```

### 2. Verificar Estado Actual del Bot
```bash
# Ver si está ganando
python manage.py estadisticas_bot --periodo 24

# Ver estado actual
python manage.py shell -c "
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()
print(f'Estado: {config.estado}')
print(f'Balance: {config.balance_actual}')
print(f'Ganancia acumulada: {config.ganancia_acumulada}')
"
```

### 3. Decidir Cuándo Aplicar Cambios

**Si el bot está ganando:**
- NO reinicies el servicio
- Deja que siga operando con la estrategia actual
- Los cambios se aplicarán cuando reinicies manualmente

**Si quieres aplicar los cambios:**
```bash
# Reiniciar servicio (esto aplicará los cambios)
sudo systemctl restart binabot-loop.service
```

## Cambios que Afectan la Estrategia

Los siguientes cambios se aplicarán cuando reinicies:

1. **Filtro de activos**: Excluye activos con winrate <30%
2. **Bonus por winrate histórico**: Prioriza activos con mejor historial
3. **Bonus por horario**: +15 puntos en horario 6:00
4. **Análisis de 60 segundos**: Cambió de 5 ticks a 60 segundos

## Opción: Pull Solo del Bot Inverso

Si solo quieres el bot inverso sin afectar el principal:

```bash
# Hacer pull completo
git pull origin main

# Hacer migraciones solo del bot inverso
python manage.py makemigrations trading_inverso
python manage.py migrate trading_inverso

# NO reiniciar binabot-loop.service (bot principal)
# Solo iniciar binabot-inverso.service (bot inverso)
```

## Verificar Qué Versión Está Corriendo

```bash
# Ver logs del bot para ver qué estrategia está usando
journalctl -u binabot-loop.service --since "10 minutes ago" --no-pager | grep -i "evaluando\|score\|activo"
```

## Recomendación

**Si el bot está ganando:**
1. Haz pull (no afecta)
2. NO reinicies el servicio
3. Deja que siga operando
4. Cuando quieras aplicar cambios, reinicia manualmente

**Si el bot está perdiendo:**
1. Haz pull
2. Reinicia el servicio para aplicar mejoras
3. Monitorea resultados

