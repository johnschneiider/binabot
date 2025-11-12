# Bot de Trading Deriv

Proyecto Django modular para automatizar un bot de trading en Deriv con lógica de metas y stop loss dinámicos, simulación de horarios, dashboard en tiempo real e integración con Twilio.

## Arquitectura

- `core`: configuración central del bot, balance, metas y gestor de estado.
- `trading`: motor de señales, ejecución de operaciones y tareas principales.
- `simulacion`: generación de operaciones ficticias y cálculo de winrate por horario.
- `historial`: modelos y API para registrar operaciones reales y simuladas, exportación CSV.
- `dashboard`: API REST (DRF) para métricas y panel.
- `notificaciones`: servicios de WhatsApp mediante Twilio.
- `integracion_deriv`: cliente WebSocket y canal para interacción con Deriv.

## Requisitos

- Python 3.12+

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración inicial

1. Copia el archivo `env.example` a `.env` y define:
   - Credenciales de Django (`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_DEBUG`).
   - Token de Deriv (`DERIV_API_TOKEN`, `DERIV_ACCOUNT_ID`, `DERIV_APP_ID`).
   - Credenciales Twilio (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`).
   - Números de destino (`WHATSAPP_NUMEROS_ALERTA` separadas por comas).

2. Ejecuta migraciones:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

3. Prepara datos iniciales desde el admin (`/admin`):
   - Da de alta los `Activos permitidos` que quieras operar.
   - La configuración del balance se tomará automáticamente de la API de Deriv una vez que hayas definido el token y `DERIV_APP_ID`.

## Ejecución local

- Servidor ASGI (HTTP + WebSocket):

  ```powershell
  uvicorn bot_deriv.asgi:application --host 127.0.0.1 --port 8000
  ```

- Loop principal del bot (sin Celery):

  ```powershell
  python manage.py ejecutar_bot --intervalo 60 --intervalo-simulacion 3600
  ```
  (`--intervalo-simulacion` controla cada cuántos segundos se recalculan los horarios mientras el bot está en pausa; el valor por defecto es 3600 s).

- Recolección de ticks reales de Deriv (ejecutar en una tercera terminal para alimentar las operaciones y las simulaciones en pausa):

  ```powershell
  python manage.py recolectar_ticks --loop
  ```
  (Puedes limitar duración y/o número de ticks con `--duracion` y `--max-ticks`. Con `--loop` permanecerá corriendo indefinidamente y escuchará todos los `ActivoPermitido` habilitados).

## Despliegue en www.vitalmix.com.co

1. **DNS**: crea registros `A` para `www.vitalmix.com.co` y `vitalmix.com.co` apuntando a la IP pública del servidor que alojará la aplicación.
2. **Variables de entorno**: define `DJANGO_ALLOWED_HOSTS=www.vitalmix.com.co,vitalmix.com.co` y `DJANGO_CSRF_TRUSTED_ORIGINS=https://www.vitalmix.com.co,https://vitalmix.com.co`. Desactiva debug con `DJANGO_DEBUG=False` y usa una `DJANGO_SECRET_KEY` robusta.
3. **Dependencias y migraciones**: ejecuta `pip install -r requirements.txt`, `python manage.py migrate` y `python manage.py collectstatic --noinput`.
4. **Servidor de aplicaciones**: levanta la app con `gunicorn bot_deriv.wsgi:application` o `daphne bot_deriv.asgi:application`, detrás de Nginx sirviendo `staticfiles/` y gestionando TLS (Let's Encrypt) para `www.vitalmix.com.co`.
5. **Servicios auxiliares**: usa `systemd`, Supervisor o equivalentes para mantener activos `python manage.py ejecutar_bot ...` y `python manage.py recolectar_ticks --loop` según tus necesidades operativas.

## Publicación en GitHub

El repositorio remoto [`johnschneiider/binabot`](https://github.com/johnschneiider/binabot.git) está vacío, por lo que puedes subir el código de este proyecto con los siguientes pasos:

```powershell
git init
git add .
git commit -m "Initial project upload"
git branch -M main
git remote add origin https://github.com/johnschneiider/binabot.git
git push -u origin main
```

Si el repositorio ya tuviera commits previos, ejecuta `git pull --rebase origin main` antes de `git push` para mantener el historial limpio.

## Dashboard

Disponible en la ruta raíz (`/`). El panel consume las APIs expuestas bajo `/api/` para métricas y estado del bot.

## Notas

- El motor de trading solo opera con datos reales de Deriv. Si el token o `DERIV_APP_ID` no son válidos, el ciclo se detendrá y registrará el error.
- El simulador de horarios utiliza únicamente ticks reales almacenados en `historial.Tick`; asegúrate de tener el recolector activo durante las pausas para que se calculen winrates válidos.

