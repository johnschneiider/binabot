from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# CARGA DE VARIABLES DE ENTORNO (.env) PARA ENTORNO LOCAL/DEV.
# IMPORTANTE:
# - En Windows/PowerShell es común que queden variables en sesión ($env:...).
# - python-dotenv NO sobrescribe por defecto, lo cual puede ignorar tu .env.
# - Usamos override=True para que .env sea la fuente de verdad en dev.
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "INSEGURO-PARA-DESARROLLO")
DEBUG = (os.getenv("DJANGO_DEBUG", "False").strip().lower() in {"1", "true", "yes", "y"})
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # APPS MODULARES (OBLIGATORIAS)
    "vector_variables",
    "vector_pesos",
    "gestion_riesgo",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "quant_deriv_bot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "quant_deriv_bot.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ===== DERIV =====
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089").strip()
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()
DERIV_ACCOUNT_ID = os.getenv("DERIV_ACCOUNT_ID", "").strip()
# Símbolo por defecto del bot. En producción se recomienda setear DERIV_SYMBOL en el entorno.
# Default: R_10 (evita crear/mostrar accidentalmente cuentas R_100 en instalaciones nuevas).
DERIV_SYMBOL = os.getenv("DERIV_SYMBOL", "R_10").strip()
DERIV_MODO_REAL = (os.getenv("DERIV_MODO_REAL", "False").strip().lower() in {"1", "true", "yes", "y"})
DERIV_CONFIRMAR_REAL = os.getenv("DERIV_CONFIRMAR_REAL", "NO").strip().upper()
DERIV_DURACION_TICKS = int(os.getenv("DERIV_DURACION_TICKS", "5"))
# Para contratos por ticks (duration_unit="t") Deriv suele limitar a 1..10 (depende del market).
# Esto evita que el bot intente enviar propuestas imposibles y quede en loop de reconexión.
DERIV_MAX_DURACION_TICKS = int(os.getenv("DERIV_MAX_DURACION_TICKS", "10"))
DERIV_MIN_STAKE = float(os.getenv("DERIV_MIN_STAKE", "1.0"))
# Si está seteado (ej: 0.5), el bot intentará usar ese stake (USD) por operación en modo real,
# respetando los límites de riesgo (no exceder riesgo_disponible ni capital_actual) y DERIV_MIN_STAKE.
_stake_fijo_raw = os.getenv("DERIV_STAKE_FIJO", "").strip()
DERIV_STAKE_FIJO = float(_stake_fijo_raw) if _stake_fijo_raw else None
DERIV_HISTORIAL_LIMIT = int(os.getenv("DERIV_HISTORIAL_LIMIT", "50"))
DERIV_HISTORIAL_CADA_SEGUNDOS = int(os.getenv("DERIV_HISTORIAL_CADA_SEGUNDOS", "10"))
BALANCE_SNAPSHOT_CADA_SEG = int(os.getenv("BALANCE_SNAPSHOT_CADA_SEG", "60"))
# Restringir qué tipos de contrato puede ejecutar el bot (ej: "PUT" para desactivar CALL).
DERIV_CONTRACT_TYPES_PERMITIDOS = [
    x.strip().upper()
    for x in os.getenv("DERIV_CONTRACT_TYPES_PERMITIDOS", "PUT,CALL").split(",")
    if x.strip()
]
# Bloqueo horario (hora local del proyecto) para evitar ventanas malas.
# Formato: "2-3,22" (rangos inclusivos). Vacío => no bloquea por horario.
DERIV_BLOQUEO_HORAS_LOCAL = os.getenv("DERIV_BLOQUEO_HORAS_LOCAL", "").strip()
# Cada cuántos segundos forzar un request "balance" (one-shot) para evitar que el bot
# quede pegado bloqueado cuando Deriv no emite updates de balance (p. ej. pausa de ciclo ya vencida).
DERIV_BALANCE_POLL_CADA_SEG = float(os.getenv("DERIV_BALANCE_POLL_CADA_SEG", "60"))

# ===== ROBUSTEZ TRADING REAL =====
# Si Deriv/WS no responde a proposal/buy o se pierde un mensaje, el bot puede quedar "pegado" en estado esperando.
# Estos timeouts activan un watchdog que resetea el estado y/o re-suscribe el contrato abierto tras reconexión.
DERIV_TIMEOUT_PROPUESTA_SEG = float(os.getenv("DERIV_TIMEOUT_PROPUESTA_SEG", "15"))
DERIV_TIMEOUT_CONTRATO_SEG = float(os.getenv("DERIV_TIMEOUT_CONTRATO_SEG", "120"))

# ===== PARÁMETROS CUANTITATIVOS =====
UMBRAL_COMPRA = float(os.getenv("UMBRAL_COMPRA", "0.75"))
UMBRAL_VENTA = float(os.getenv("UMBRAL_VENTA", "-0.75"))
VENTANA_RETORNOS = int(os.getenv("VENTANA_RETORNOS", "200"))
VENTANA_TICKS_RATE = int(os.getenv("VENTANA_TICKS_RATE", "60"))
MIN_TICKS_CALENTAMIENTO = int(os.getenv("MIN_TICKS_CALENTAMIENTO", "100"))
STOP_MIN_PORCENTAJE = float(os.getenv("STOP_MIN_PORCENTAJE", "0.001"))

# ===== NORMALIZACIÓN (PARA QUE w^T x SEA ESTABLE) =====
NORMALIZAR_VECTOR = (os.getenv("NORMALIZAR_VECTOR", "True").strip().lower() in {"1", "true", "yes", "y"})
NORMALIZACION_ALPHA = float(os.getenv("NORMALIZACION_ALPHA", "0.01"))
NORMALIZACION_MIN_STD = float(os.getenv("NORMALIZACION_MIN_STD", "1e-8"))
NORMALIZACION_CLIP = float(os.getenv("NORMALIZACION_CLIP", "5.0"))
SENAL_TOP_N = int(os.getenv("SENAL_TOP_N", "5"))

# ===== ESTRATEGIA =====
# Tipo de estrategia: "vectores" (antigua con w^T x) o "extremos" (nueva basada en máximos/mínimos)
ESTRATEGIA_TIPO = os.getenv("ESTRATEGIA_TIPO", "extremos").strip().lower()
# Umbral mínimo de rango para operar con estrategia de extremos
ESTRATEGIA_EXTREMOS_UMBRAL_RANGO = float(os.getenv("ESTRATEGIA_EXTREMOS_UMBRAL_RANGO", "0.5"))
# Cooldown después de cada operación (en ticks)
ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS = int(os.getenv("ESTRATEGIA_EXTREMOS_COOLDOWN_TICKS", "25"))

# ===== ESTRATEGIA EXTREMOS (CONFIG AVANZADA) =====
# Ventana de ticks para calcular máximos/mínimos.
EXTREMOS_VENTANA_TICKS = int(os.getenv("EXTREMOS_VENTANA_TICKS", "100"))
# Cuántos ticks hacia atrás se considera "fresco" un extremo.
EXTREMOS_FRESCURA_TICKS = int(os.getenv("EXTREMOS_FRESCURA_TICKS", "5"))
# Ventana para contar repeticiones de extremos (anti-consolidación).
EXTREMOS_VENTANA_REPETICIONES = int(os.getenv("EXTREMOS_VENTANA_REPETICIONES", "10"))
# Máximo de repeticiones del extremo dentro de EXTREMOS_VENTANA_REPETICIONES.
EXTREMOS_MAX_REPETICIONES = int(os.getenv("EXTREMOS_MAX_REPETICIONES", "2"))
# Anti “continuación de tendencia”:
# Exige que el precio se aleje del extremo al menos un delta mínimo antes de entrar.
# min_reversion = max(EXTREMOS_MIN_REVERSION_ABS, EXTREMOS_MIN_REVERSION_FRAC * rango)
EXTREMOS_MIN_REVERSION_FRAC = float(os.getenv("EXTREMOS_MIN_REVERSION_FRAC", "0.05"))
EXTREMOS_MIN_REVERSION_ABS = float(os.getenv("EXTREMOS_MIN_REVERSION_ABS", "0.0"))
# Filtro adicional (confirmación 2-ticks):
# Exige que el retroceso desde el extremo sea mayor que el “ruido” típico reciente
# (promedio de |delta| en los últimos K ticks), multiplicado por un factor.
EXTREMOS_PROMEDIO_DELTA_TICKS = int(os.getenv("EXTREMOS_PROMEDIO_DELTA_TICKS", "20"))
EXTREMOS_PROMEDIO_DELTA_FACTOR = float(os.getenv("EXTREMOS_PROMEDIO_DELTA_FACTOR", "1.0"))

# ===== PESOS (ESTRATEGIA) =====
# ARCHIVO JSON QUE EL BOT PUEDE RECARGAR EN CALIENTE PARA ACTUALIZAR w SIN REDEPLOY.
PESOS_ARCHIVO = os.getenv("PESOS_ARCHIVO", str(BASE_DIR / "vector_pesos" / "pesos_calibrados.json")).strip()

# ===== ADAPTADOR ONLINE (AUTO-UMBRAL) =====
ADAPTATIVO_HABILITADO = (os.getenv("ADAPTATIVO_HABILITADO", "False").strip().lower() in {"1", "true", "yes", "y"})
ADAPTATIVO_ARCHIVO = os.getenv(
    "ADAPTATIVO_ARCHIVO", str(BASE_DIR / "vector_pesos" / "umbral_online.json")
).strip()
ADAPTATIVO_UMBRALES = [
    float(x.strip())
    for x in os.getenv("ADAPTATIVO_UMBRALES", "0.05,0.07,0.09,0.11,0.13,0.15").split(",")
    if x.strip()
]
# Guardrails del adaptador (conservadores por defecto)
ADAPTATIVO_MIN_TRADES = int(os.getenv("ADAPTATIVO_MIN_TRADES", "60"))
ADAPTATIVO_EDGE_MARGIN = float(os.getenv("ADAPTATIVO_EDGE_MARGIN", "0.02"))
# Mientras el adaptador no tenga evidencia suficiente, puede:
# - "no_operar" (seguro) o
# - "warmup" (operar con un umbral inicial fijo para recolectar datos)
ADAPTATIVO_MODO_SIN_EVIDENCIA = os.getenv("ADAPTATIVO_MODO_SIN_EVIDENCIA", "no_operar").strip().lower()
ADAPTATIVO_UMBRAL_WARMUP = float(os.getenv("ADAPTATIVO_UMBRAL_WARMUP", "0.09"))

# ===== CALIBRADOR WALK-FORWARD =====
CALIBRADOR_TICKS_COUNT = int(os.getenv("CALIBRADOR_TICKS_COUNT", "5000"))
CALIBRADOR_TRAIN_TICKS = int(os.getenv("CALIBRADOR_TRAIN_TICKS", "2000"))
CALIBRADOR_TEST_TICKS = int(os.getenv("CALIBRADOR_TEST_TICKS", "500"))
CALIBRADOR_LAMBDA_RIDGE = float(os.getenv("CALIBRADOR_LAMBDA_RIDGE", "1.0"))
CALIBRADOR_HORIZON_TICKS = int(os.getenv("CALIBRADOR_HORIZON_TICKS", str(DERIV_DURACION_TICKS)))

# ===== CALIBRADOR (EVALUACIÓN OOS REALISTA PARA BINARIAS) =====
# Payout aproximado por trade ganador en unidades de stake=1 (ej: 0.95 => gana 0.95, pierde 1.0).
CALIBRADOR_PAYOUT_WIN = float(os.getenv("CALIBRADOR_PAYOUT_WIN", "0.95"))
# Costo aproximado por trade (slippage/fees/spread) en unidades de stake=1.
CALIBRADOR_COSTO_POR_TRADE = float(os.getenv("CALIBRADOR_COSTO_POR_TRADE", "0.0"))
# Guardrails: rechazar umbrales que generen muy pocos trades o demasiado drawdown en test.
CALIBRADOR_MIN_TRADES_TEST = int(os.getenv("CALIBRADOR_MIN_TRADES_TEST", "10"))
CALIBRADOR_MAX_DD_TEST = float(os.getenv("CALIBRADOR_MAX_DD_TEST", "10.0"))
CALIBRADOR_MAX_TRADE_RATE = float(os.getenv("CALIBRADOR_MAX_TRADE_RATE", "0.20"))
# target por defecto: dirección (mejor escala para umbrales tipo 0.75)
CALIBRADOR_TARGET = os.getenv("CALIBRADOR_TARGET", "sign").strip().lower()
# Margen mínimo sobre el break-even winrate (por payout/costo) para aceptar umbrales.
CALIBRADOR_MIN_EDGE_WINRATE = float(os.getenv("CALIBRADOR_MIN_EDGE_WINRATE", "0.02"))

# ===== RIESGO =====
CAPITAL_INICIAL = float(os.getenv("CAPITAL_INICIAL", "100.0"))
MAX_RIESGO_POR_OPERACION = float(os.getenv("MAX_RIESGO_POR_OPERACION", "0.01"))
MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.20"))
# Histéresis para evitar “flip-flop” cerca del umbral:
# - Bloquea cuando drawdown >= MAX_DRAWDOWN
# - Desbloquea cuando drawdown <= (MAX_DRAWDOWN - MAX_DRAWDOWN_HISTERESIS)
# Si es 0.0, se comporta como antes.
MAX_DRAWDOWN_HISTERESIS = float(os.getenv("MAX_DRAWDOWN_HISTERESIS", "0.0"))
# Si estás usando “modo ciclos”, normalmente conviene desactivar el drawdown global histórico.
DRAWDOWN_GLOBAL_HABILITADO = (os.getenv("DRAWDOWN_GLOBAL_HABILITADO", "True").strip().lower() in {"1", "true", "yes", "y"})

# ===== CICLOS (MODO REAL) =====
# Gobernanza simple por ciclos:
# - baseline = balance al iniciar ciclo
# - take profit => pausa 24h y reinicia ciclo al reanudar
# - stoploss => pausa 1h y reinicia ciclo al reanudar
CICLO_HABILITADO = (os.getenv("CICLO_HABILITADO", "False").strip().lower() in {"1", "true", "yes", "y"})
CICLO_TAKE_PROFIT_PCT = float(os.getenv("CICLO_TAKE_PROFIT_PCT", "0.015"))
CICLO_STOPLOSS_PCT = float(os.getenv("CICLO_STOPLOSS_PCT", "0.010"))
CICLO_PAUSA_TP_SEG = int(os.getenv("CICLO_PAUSA_TP_SEG", "86400"))
CICLO_PAUSA_SL_SEG = int(os.getenv("CICLO_PAUSA_SL_SEG", "3600"))


