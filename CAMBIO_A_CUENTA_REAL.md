# Guía para Cambiar de Cuenta Demo a Cuenta Real en Deriv

## ⚠️ ADVERTENCIA IMPORTANTE

**Operar con dinero real implica riesgos financieros reales.**
- Asegúrate de haber probado exhaustivamente el bot en cuenta demo
- Verifica que todas las configuraciones de riesgo estén correctas
- Comienza con montos pequeños para validar el funcionamiento
- Monitorea de cerca las primeras operaciones

## 📋 Pasos para Cambiar a Cuenta Real

### 1. Obtener Credenciales de Cuenta Real

1. Inicia sesión en tu cuenta **REAL** de Deriv
2. Ve a **Configuración → API** (o **Settings → API**)
3. Genera un nuevo token de API para cuenta real
4. Copia el **Token de API** y el **Account ID** (si está disponible)

### 2. Actualizar el Archivo `.env`

Edita el archivo `.env` en tu servidor:

```bash
# En la VPS
nano /var/www/vitalmix.com.co/app/.env
```

**Cambiar estas variables:**

```env
# ❌ ANTES (Cuenta Demo)
DERIV_API_TOKEN=WwPVsJ7gJZ7KHW2
DERIV_ACCOUNT_ID=tu_account_id_demo
DERIV_APP_ID=1089

# ✅ DESPUÉS (Cuenta Real)
DERIV_API_TOKEN=tu_token_real_aqui
DERIV_ACCOUNT_ID=tu_account_id_real
DERIV_APP_ID=1089
```

**Nota:** El `DERIV_APP_ID` generalmente es el mismo (`1089`) para demo y real, pero verifica en la documentación de Deriv.

### 3. Verificar Configuración de Riesgo

Antes de reiniciar, verifica que las configuraciones de riesgo estén adecuadas:

```bash
# Conectarse a Django shell
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate
python manage.py shell
```

En el shell:
```python
from core.models import ConfiguracionBot
config = ConfiguracionBot.obtener()

# Verificar configuración actual
print(f"Balance actual: {config.balance_actual}")
print(f"Meta actual: {config.meta_actual}")
print(f"Stop loss actual: {config.stop_loss_actual}")
print(f"Monto por trade (%): {config.MONTO_TRADE_PORCENTAJE * 100}%")
```

**Ajustes recomendados para cuenta real:**
- **Monto por trade:** Considera reducir el porcentaje (por defecto es 0.5%)
- **Stop loss:** Asegúrate de que esté configurado correctamente
- **Meta:** Configura metas realistas

### 4. Reiniciar los Servicios

```bash
# Detener todos los servicios
sudo systemctl stop binabot-loop.service
sudo systemctl stop binabot-ticks.service
sudo systemctl stop binabot.service

# Esperar unos segundos
sleep 5

# Reiniciar servicios
sudo systemctl start binabot.service
sudo systemctl start binabot-ticks.service
sudo systemctl start binabot-loop.service

# Verificar que están corriendo
sudo systemctl status binabot-loop.service
sudo systemctl status binabot-ticks.service
sudo systemctl status binabot.service
```

### 5. Verificar que Funciona Correctamente

#### a) Verificar conexión con la API:

```bash
# Ver logs del bot
sudo journalctl -u binabot-loop.service -f
```

Deberías ver mensajes como:
- `Bot iniciado correctamente`
- `Balance sincronizado: $XXX.XX`
- Sin errores de autenticación

#### b) Verificar balance en el dashboard:

1. Abre el dashboard en tu navegador
2. Verifica que el balance mostrado corresponde a tu cuenta **REAL**
3. Confirma que no hay errores en la consola del navegador (F12)

#### c) Probar una operación pequeña (opcional):

Si quieres probar antes de dejar el bot operando automáticamente:

```bash
# Ejecutar un ciclo manual del bot
cd /var/www/vitalmix.com.co/app/src
source /var/www/vitalmix.com.co/app/.venv/bin/activate
python manage.py ejecutar_bot --intervalo 60 --profesional
# Presiona Ctrl+C después de ver una operación
```

## 🔍 Verificación de Diferencias Demo vs Real

### Lo que NO cambia:
- ✅ La URL del WebSocket (`wss://ws.derivws.com/websockets/v3`)
- ✅ El `DERIV_APP_ID` (generalmente `1089`)
- ✅ La lógica del bot
- ✅ Los símbolos disponibles

### Lo que SÍ cambia:
- ❌ El `DERIV_API_TOKEN` (debe ser el token de cuenta real)
- ❌ El `DERIV_ACCOUNT_ID` (debe ser el ID de cuenta real)
- ❌ El balance (será el balance real de tu cuenta)
- ❌ Las operaciones (serán reales y afectarán tu balance real)

## 🛡️ Configuraciones de Seguridad Recomendadas

### 1. Montos de Trade Conservadores

En `core/models.py`, el porcentaje por defecto es `0.5%` del balance. Para cuenta real, considera:

- **Conservador:** 0.1% - 0.2%
- **Moderado:** 0.3% - 0.5%
- **Agresivo:** 0.5% - 1% (no recomendado para empezar)

### 2. Stop Loss Estricto

Asegúrate de que el stop loss esté configurado. Por defecto es `5%` del balance base.

### 3. Límites Diarios

Considera agregar límites diarios de pérdidas o ganancias para proteger tu capital.

### 4. Monitoreo Activo

- Revisa el dashboard regularmente
- Configura alertas de WhatsApp para operaciones importantes
- Monitorea los logs del bot

## 🚨 Señales de Alerta

Si ves estos errores, **DETÉN EL BOT INMEDIATAMENTE**:

```
Error: Invalid token
Error: Authentication failed
Error: Insufficient balance
Error: Account not authorized
```

## 📝 Checklist Final

Antes de dejar el bot operando con dinero real:

- [ ] Token de API real configurado en `.env`
- [ ] Account ID real configurado
- [ ] Balance en el dashboard corresponde a cuenta real
- [ ] Configuraciones de riesgo revisadas y ajustadas
- [ ] Servicios reiniciados y funcionando
- [ ] Logs sin errores de autenticación
- [ ] Dashboard muestra datos correctos
- [ ] Has probado al menos una operación pequeña manualmente
- [ ] Alertas de WhatsApp configuradas
- [ ] Tienes acceso para detener el bot rápidamente si es necesario

## 🔄 Volver a Cuenta Demo

Si necesitas volver a cuenta demo:

1. Edita `.env` y restaura el token de demo
2. Reinicia los servicios
3. Verifica que el balance vuelve a ser el de demo

## 📞 Soporte

Si encuentras problemas:
1. Revisa los logs: `sudo journalctl -u binabot-loop.service -n 100`
2. Verifica la configuración: `python manage.py shell` → `from core.models import ConfiguracionBot; print(ConfiguracionBot.obtener().__dict__)`
3. Consulta la documentación de Deriv API

---

**Recuerda:** El trading conlleva riesgos. Nunca operes con dinero que no puedas permitirte perder.

