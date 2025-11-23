# Solución al Problema de Pausa Incorrecta

## Problema Identificado

El bot se pausó incorrectamente a las **01:04:50** estando en ganancia. Los logs no muestran el motivo exacto, pero el análisis revela:

1. **Última operación antes de pausa**: 01:03:47 (RDBEAR PUT - loss)
2. **Balance en ese momento**: Aproximadamente $85.48 (después de la pérdida)
3. **Stop loss en ese momento**: Aproximadamente $84.55 (98% de $86.28)
4. **El balance ($85.48) estaba POR ENCIMA del stop loss ($84.55)**

## Causa Raíz

El problema estaba en `core/services.py`, línea 296, donde `sincronizar_balance_desde_api()` **siempre** llamaba a `_verificar_stop_loss()` después de sincronizar el balance, incluso cuando:
- El bot ya estaba pausado
- El balance estaba por encima del stop loss
- Había una sincronización desactualizada

Esto podía causar pausas incorrectas si:
1. El balance sincronizado desde Deriv estaba temporalmente desactualizado
2. Había una discrepancia entre el balance en BD y el balance en Deriv
3. El stop loss se calculaba incorrectamente durante la sincronización

## Corrección Aplicada

Se modificó `core/services.py` para que `_verificar_stop_loss()` solo se llame si:
1. El bot está **OPERANDO** (no si ya está pausado)
2. El balance **realmente** está por debajo del stop loss

```python
# ANTES (INCORRECTO):
self._verificar_stop_loss()  # Siempre verificaba, incluso durante sincronizaciones

# DESPUÉS (CORRECTO):
if self.configuracion.estado == ConfiguracionBot.Estado.OPERANDO:
    if self.configuracion.balance_actual <= self.configuracion.stop_loss_actual:
        self._verificar_stop_loss()  # Solo verifica si realmente está por debajo
```

## Verificación

Para verificar que la corrección funciona:

```bash
# 1. Verificar que el bot está operando
python manage.py shell -c "from core.models import ConfiguracionBot; c=ConfiguracionBot.obtener(); print(f'Estado: {c.estado}, Balance: \${c.balance_actual:.2f}, Stop Loss: \${c.stop_loss_actual:.2f}')"

# 2. Monitorear los logs en tiempo real
sudo journalctl -u binabot-loop.service -f

# 3. Verificar que no se pausa incorrectamente
# El bot solo debería pausarse después de una pérdida que realmente cause que el balance caiga por debajo del stop loss
```

## Prevención Futura

Para evitar pausas incorrectas en el futuro:

1. **Solo verificar stop loss después de pérdidas registradas**: Ya implementado en `registrar_perdida()`
2. **No verificar durante sincronizaciones**: Ya corregido
3. **Logging mejorado**: Agregar logging cuando se pausa para rastrear la causa

## Comandos de Monitoreo

```bash
# Ver logs en tiempo real
sudo journalctl -u binabot-loop.service -f

# Ver si hay pausas
sudo journalctl -u binabot-loop.service --since "1 hour ago" --no-pager | grep -i "pausa\|pausado"

# Verificar estado del bot
python manage.py diagnosticar_bots
```

## Nota Importante

El bot ya fue reanudado manualmente. Con la corrección aplicada, el bot NO debería pausarse incorrectamente durante sincronizaciones de balance. La pausa solo debería ocurrir cuando:
1. Hay una pérdida registrada
2. El balance realmente cae por debajo del stop loss
3. NO durante sincronizaciones normales

