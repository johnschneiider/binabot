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

# ===== BASE DE DATOS =====
# Soporta PostgreSQL (producción) y SQLite (desarrollo)
# Configurar en .env:
#   DB_ENGINE=postgresql (producción)
#   DB_ENGINE=sqlite3 (desarrollo)
DB_ENGINE = os.getenv("DB_ENGINE", "sqlite3").strip()

if DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "binary_bot").strip(),
            "USER": os.getenv("DB_USER", "bot_user").strip(),
            "PASSWORD": os.getenv("DB_PASSWORD", "").strip(),
            "HOST": os.getenv("DB_HOST", "localhost").strip(),
            "PORT": os.getenv("DB_PORT", "5432").strip(),
            "CONN_MAX_AGE": 60,
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # THIRD-PARTY
    "rest_framework",
    # APPS MODULARES (OBLIGATORIAS)
    "vector_variables",
    "vector_pesos",
    "gestion_riesgo",
    # APP DE SUSCRIPCIONES (Multi-tenant)
    "subscriptions",
    # PÁGINAS PÚBLICAS
    "pages",
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
        "DIRS": [BASE_DIR / "templates"],
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

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ===== AUTENTICACION =====
# Modelo de usuario custom para multi-tenant
AUTH_USER_MODEL = "subscriptions.Usuario"

# ===== DERIV =====
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089").strip()
DERIV_API_TOKEN = os.getenv("DERIV_API_TOKEN", "").strip()
DERIV_ACCOUNT_ID = os.getenv("DERIV_ACCOUNT_ID", "").strip()
# Símbolo por defecto del bot. En producción se recomienda setear DERIV_SYMBOL en el entorno.
# Default: R_10 (evita crear/mostrar accidentalmente cuentas R_100 en instalaciones nuevas).
DERIV_SYMBOL = os.getenv("DERIV_SYMBOL", "frxEURUSD").strip()
DERIV_MODO_REAL = (os.getenv("DERIV_MODO_REAL", "False").strip().lower() in {"1", "true", "yes", "y"})
DERIV_CONFIRMAR_REAL = os.getenv("DERIV_CONFIRMAR_REAL", "NO").strip().upper()
DERIV_DURACION_TICKS = int(os.getenv("DERIV_DURACION_TICKS", "5"))
# Para contratos por ticks (duration_unit="t") Deriv suele limitar a 1..10 (depende del market).
# Esto evita que el bot intente enviar propuestas imposibles y quede en loop de reconexión.
DERIV_MAX_DURACION_TICKS = int(os.getenv("DERIV_MAX_DURACION_TICKS", "10"))
DERIV_MIN_STAKE = float(os.getenv("DERIV_MIN_STAKE", "1.0"))
DERIV_MIN_STAKE_DINAMICO = float(os.getenv("DERIV_MIN_STAKE_DINAMICO", "0.35"))
DERIV_DUR_ABS_MAX = int(os.getenv("DERIV_DUR_ABS_MAX", "10"))
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
TICKS_HIST_FLUSH_EVERY = int(os.getenv("TICKS_HIST_FLUSH_EVERY", "25"))
TICKS_HIST_FLUSH_SECS = float(os.getenv("TICKS_HIST_FLUSH_SECS", "5.0"))

# ===== ESTRATEGIA SPP (estructura + pendiente + pullback) =====
# Estos valores se consumen desde `vector_pesos/senal_spp.py`.
# Defaults conservadores ("modo banco"): menos trades, más selectividad.
SPP_SLOPE_N = int(os.getenv("SPP_SLOPE_N", "7"))
SPP_PULLBACK_MIN_TICKS = int(os.getenv("SPP_PULLBACK_MIN_TICKS", "4"))
SPP_PULLBACK_MAX_TICKS = int(os.getenv("SPP_PULLBACK_MAX_TICKS", "7"))
SPP_PULLBACK_DIST_FACTOR = float(os.getenv("SPP_PULLBACK_DIST_FACTOR", "0.45"))
SPP_COOLDOWN_TICKS = int(os.getenv("SPP_COOLDOWN_TICKS", "80"))
SPP_DYNAMIC_COOLDOWN = os.getenv("SPP_DYNAMIC_COOLDOWN", "true").lower() == "true"
SPP_FATIGA_PRDIDAS = int(os.getenv("SPP_FATIGA_PRDIDAS", "3"))
SPP_FATIGA_MULTIPLICADOR = float(os.getenv("SPP_FATIGA_MULTIPLICADOR", "1.5"))
SPP_CHOPPY_WINDOW = int(os.getenv("SPP_CHOPPY_WINDOW", "20"))
SPP_CHOPPY_MAX_FLIPS = int(os.getenv("SPP_CHOPPY_MAX_FLIPS", "10"))
SPP_ESTRUCTURA_WINDOW = int(os.getenv("SPP_ESTRUCTURA_WINDOW", "24"))

# Umbrales por activo
SPP_SLOPE_THRESHOLD_R10 = float(os.getenv("SPP_SLOPE_THRESHOLD_R10", "0.04"))
SPP_MIN_EMA_GAP_R10 = float(os.getenv("SPP_MIN_EMA_GAP_R10", "0.08"))
SPP_SLOW_SLOPE_EPS_R10 = float(os.getenv("SPP_SLOW_SLOPE_EPS_R10", "0.0"))
SPP_ESTRUCTURA_MIN_DELTA_R10 = float(os.getenv("SPP_ESTRUCTURA_MIN_DELTA_R10", "0.03"))
SPP_RETAKE_MIN_DELTA_R10 = float(os.getenv("SPP_RETAKE_MIN_DELTA_R10", "0.015"))

SPP_SLOPE_THRESHOLD_R100 = float(os.getenv("SPP_SLOPE_THRESHOLD_R100", "0.18"))
SPP_MIN_EMA_GAP_R100 = float(os.getenv("SPP_MIN_EMA_GAP_R100", "0.35"))
SPP_SLOW_SLOPE_EPS_R100 = float(os.getenv("SPP_SLOW_SLOPE_EPS_R100", "0.0"))
SPP_ESTRUCTURA_MIN_DELTA_R100 = float(os.getenv("SPP_ESTRUCTURA_MIN_DELTA_R100", "0.15"))
SPP_RETAKE_MIN_DELTA_R100 = float(os.getenv("SPP_RETAKE_MIN_DELTA_R100", "0.06"))

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

# ===== MODELOS ML (LightGBM) =====
LGBM_MODEL_R10 = os.getenv("LGBM_MODEL_R10", "").strip()
LGBM_MODEL_R100 = os.getenv("LGBM_MODEL_R100", "").strip()
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

# ===== EDGE GUARD (modo institucional) =====
# Circuit breaker basado en performance reciente: si la expectativa estimada es negativa,
# el bot se pausa automáticamente un tiempo para evitar “tilt loops”.
EDGE_GUARD_HABILITADO = (os.getenv("EDGE_GUARD_HABILITADO", "True").strip().lower() in {"1", "true", "yes", "y"})
EDGE_GUARD_WINDOW_N = int(os.getenv("EDGE_GUARD_WINDOW_N", "200"))          # ventana de trades cerrados
EDGE_GUARD_MIN_TRADES = int(os.getenv("EDGE_GUARD_MIN_TRADES", "60"))       # no actuar con poca data
EDGE_GUARD_MARGIN_WR = float(os.getenv("EDGE_GUARD_MARGIN_WR", "0.015"))    # margen vs breakeven
EDGE_GUARD_PAUSA_SEG = int(os.getenv("EDGE_GUARD_PAUSA_SEG", "3600"))       # 1h
EDGE_GUARD_MIN_LOSS_STREAK = int(os.getenv("EDGE_GUARD_MIN_LOSS_STREAK", "5"))

# ===== LIMITADOR DE SESIÓN (anti-overtrading) =====
RISK_MAX_TRADES_PER_HOUR = int(os.getenv("RISK_MAX_TRADES_PER_HOUR", "0"))  # 0=deshabilitado
RISK_MAX_TRADES_PER_DAY = int(os.getenv("RISK_MAX_TRADES_PER_DAY", "0"))    # 0=deshabilitado

# ===== DJANGO REST FRAMEWORK =====
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "VIEW_DESCRIPTION_FUNCTION": "rest_framework.views.get_view_description",
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}


