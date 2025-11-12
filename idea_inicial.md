Quiero que crees un proyecto completo en Django + PostgreSQL y lo organices de forma modular siguiendo exactamente las siguientes especificaciones. Usa nombres de aplicaciones y archivos en español y una arquitectura limpia, escalable y desacoplada.

✅ Objetivo general del bot

Construir un bot de trading para Deriv con esta api en cuenta demo saTKimSGMgHEbh3  que opere con un sistema de meta dinámica, stop loss dinámico, monto de trade dinámico, auto-pausas inteligentes y sistema de backtesting automático por horarios.

El bot opera con reglas estrictas y debe integrarse con Twilio para notificaciones por WhatsApp.

✅ Reglas de la estrategia (ENUNCIADO OFICIAL)

El stop loss debe ser dinámico.

El stop loss se mueve junto al balance en tiempo real.

Si el balance sube, el SL sube.

Nunca baja.

Monto del trade = 0.5% del balance actual.

Meta = 1% del balance actual.

Cada vez que el bot alcanza la meta:

NO se detiene

recalcula nueva meta = 1% del nuevo balance

recalcula nuevo stop loss = 1% del nuevo balance

Cuando el precio toca el stop loss:

El bot se detiene completamente hasta el siguiente día.

Durante la pausa:

El bot hace entradas ficticias (sin enviar órdenes reales)

Guarda en BD todas esas operaciones ficticias

Calcula qué horario tiene mejor winrate

Al llegar 24h exactas desde la pausa, vuelve a activarse y espera el mejor horario encontrado

La base de datos debe almacenar:

nombre del activo

dirección (CALL/PUT)

precio de entrada

monto invertido

% de confianza

resultado de la operación (win/loss)

número del contrato

hora de inicio

hora de fin

debe poder exportarse a CSV

Dashboard: tarjeta con WON / LOSS

Mostrar:

cuántas ganadas CALL

cuántas ganadas PUT

cuántas perdidas CALL

cuántas perdidas PUT

Mostrar estado del bot: “operando / pausado”.

Mostrar contador:

hace cuánto tiempo se detuvo

a qué hora finaliza la espera.

Durante la pausa, tabla con resultados del testing y horario con mejor winrate.

Tarjeta con winrate total actual.

Tarjeta con balance actual.

El bot solo puede operar un activo a la vez y debe esperar a que termine la operación para analizar la siguiente entrada.

Integración con Twilio WhatsApp:

enviar notificación cuando el bot comienza a operar

enviar notificación cuando el bot se detiene por stop loss

números: +573158353029 y +573117451274

✅ Estructura del proyecto (obligatoria)

Crea un proyecto Django modular con las siguientes apps:

✅ core

Configuración central del bot

Manejo del balance

Cálculo de meta y stop loss

Manager de estado del bot (operando/pausa)

✅ trading

Motor de señales

Envío de órdenes reales a Deriv

Evaluación de resultados

Repositorio para lógica de trading

✅ simulacion

Generación de operaciones ficticias

Cálculo de winrate por horario

Determinación del mejor horario para reactivar el bot

✅ historial

Modelos para guardar operaciones reales y ficticias

Exportación a CSV

✅ dashboard

API REST (DRF) para métricas

Endpoints para:

winrate

estado del bot

históricos

balance

estadísticas CALL/PUT

estado del temporizador

✅ notificaciones

Enviar WhatsApp con Twilio

Servicios:

notificar_inicio_operativa()

notificar_stop_loss()

✅ integracion_deriv

Cliente WebSocket

Validación de contratos

Manejo de reconexión automática

✅ Requerimientos técnicos
✅ Backend

Django 5+

Django Rest Framework

PostgreSQL

Tareas asíncronas con Celery + Redis

WebSockets para conexión con Deriv

Worker que gestione el loop principal de trading

✅ Frontend

Django templates o React (elige la mejor alternativa)

Panel con tarjetas y tabla en tiempo real

✅ Cálculos obligatorios
🔹 Monto de trade:
trade_amount = balance_actual * 0.005

🔹 Meta:
meta = balance_actual * 0.01

🔹 Stop loss:
stop_loss = balance_actual * 0.01

🔹 Recalcular meta y SL al alcanzar la meta:
balance_actual += ganancia
meta = balance_actual * 0.01
stop_loss = balance_actual * 0.01

🔹 Condición de pausa:
if perdida_acumulada >= stop_loss:
    pausar_bot()

✅ Flujo de operación obligatorio

Iniciar bot → enviar notificación WhatsApp.

Calcular meta y stop loss.

Elegir el mejor activo disponible.

Hacer análisis → generar señal.

Enviar operación a Deriv.

Esperar resultado.

Registrar operación en BD.

Actualizar balance.

Si se alcanzó la meta → recalcular meta & SL.

Si se alcanzó stop loss →

pausar 24h

iniciar simulación por horarios

guardar horarios con mejor winrate

enviar notificación WhatsApp

Después de 24h → reactivar bot → esperar mejor horario detectado.

✅ Resultados esperados

Cursor debe:

✅ generar proyecto Django completo
✅ generar modelos, vistas, serializers, endpoints
✅ implementar cálculos del sistema dinámico
✅ implementar motor de trading conectado a Deriv
✅ implementar simulador ficticio
✅ implementar exportación CSV
✅ crear dashboards y métricas
✅ integrar Twilio
✅ dejar el proyecto listo para correr