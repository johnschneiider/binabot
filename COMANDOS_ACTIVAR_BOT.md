# Cómo Activar el Bot

## 1. Verificar Estado Actual

Primero, verifica qué está pasando con el bot:

```bash
# Verificar estado en la base de datos y servicios
python manage.py verificar_procesos
```

Esto te mostrará:
- Estado del bot en la BD (OPERANDO o PAUSADO)
- Estado de los servicios systemd
- Procesos Python en ejecución

---

## 2. Situaciones y Soluciones

### Situación A: Bot está PAUSADO en la BD

Si el bot está pausado (por stop loss o manualmente), tienes 2 opciones:

#### Opción 1: Reactivación Manual (Inmediata)

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
from core.services import GestorBotCore

config = ConfiguracionBot.obtener()
print(f'Estado actual: {config.estado}')
print(f'Balance: {config.balance_actual}')
print(f'Stop loss: {config.stop_loss_actual}')

# Reactivar manualmente
gestor = GestorBotCore()
gestor.reanudar_operativa()
print('✅ Bot reactivado manualmente')
print(f'Nuevo estado: {config.estado}')
print(f'Nuevo stop loss: {config.stop_loss_actual}')
"
```

#### Opción 2: Esperar Reactivación Automática

El bot se reactivará automáticamente cuando:
- Pasen 24 horas desde `pausado_desde`
- Si hay un `mejor_horario`, esperará a esa hora
- El loop principal verifica esto cada 60 segundos

Para ver cuándo se reactivará:

```bash
python manage.py shell -c "
from core.models import ConfiguracionBot
from django.utils import timezone

config = ConfiguracionBot.obtener()
if config.estado == 'pausado':
    print(f'Pausado desde: {config.pausado_desde}')
    if config.pausa_finaliza:
        ahora = timezone.now()
        restante = config.pausa_finaliza - ahora
        horas = int(restante.total_seconds() / 3600)
        minutos = int((restante.total_seconds() % 3600) / 60)
        print(f'Se reactivará en: {horas}h {minutos}m')
        if config.mejor_horario:
            print(f'Mejor horario: {config.mejor_horario}')
            print(f'Esperará hasta esa hora para reactivarse')
else:
    print('Bot no está pausado')
"
```

---

### Situación B: Servicios Systemd Detenidos

Si los servicios están detenidos, inícialos:

```bash
# Iniciar el servicio principal del bot
sudo systemctl start binabot-loop.service

# Iniciar el servicio de recolección de ticks
sudo systemctl start binabot-ticks.service

# Verificar que estén activos
sudo systemctl status binabot-loop.service
sudo systemctl status binabot-ticks.service
```

Para que se inicien automáticamente al reiniciar el servidor:

```bash
sudo systemctl enable binabot-loop.service
sudo systemctl enable binabot-ticks.service
```

---

### Situación C: Bot en OPERANDO pero No Ejecutándose

Si el estado es OPERANDO pero no hay procesos corriendo:

```bash
# Reiniciar los servicios
sudo systemctl restart binabot-loop.service
sudo systemctl restart binabot-ticks.service

# O usar el botón del dashboard
# (Botón "🔄 Reiniciar Bot" en el navbar)
```

---

## 3. Verificar que Todo Esté Funcionando

Después de activar, verifica:

```bash
# Ver logs en tiempo real
journalctl -u binabot-loop.service -f

# Ver estado de servicios
sudo systemctl status binabot-loop.service

# Verificar estado en BD
python manage.py shell -c "
from core.models import ConfiguracionBot
c = ConfiguracionBot.obtener()
print(f'Estado: {c.estado}')
print(f'En operación: {c.en_operacion}')
print(f'Balance: {c.balance_actual}')
print(f'Stop loss: {c.stop_loss_actual}')
"
```

---

## 4. Comandos Rápidos de Referencia

```bash
# Verificar todo
python manage.py verificar_procesos

# Reactivar manualmente (si está pausado)
python manage.py shell -c "from core.services import GestorBotCore; GestorBotCore().reanudar_operativa(); print('✅ Reactivado')"

# Iniciar servicios
sudo systemctl start binabot-loop.service binabot-ticks.service

# Reiniciar servicios
sudo systemctl restart binabot-loop.service binabot-ticks.service

# Ver logs
journalctl -u binabot-loop.service -f --since "10 minutes ago"
```

---

## 5. Desde el Dashboard Web

También puedes usar el dashboard:

1. **Ver estado**: El dashboard muestra el estado actual del bot
2. **Reiniciar servicios**: Usa el botón "🔄 Reiniciar Bot" en el navbar
3. **Ver logs**: Revisa las operaciones recientes en el panel

---

## Notas Importantes

- **Si el bot está pausado por stop loss**: Al reactivarlo manualmente, el stop loss se recalcula al 98% del balance actual (nuevo punto de partida)
- **El bot se reactiva automáticamente**: Si esperas, se reactivará después de 24 horas (o en el mejor horario si está configurado)
- **Los servicios deben estar corriendo**: Aunque el bot esté en OPERANDO, necesita que los servicios systemd estén activos para funcionar

