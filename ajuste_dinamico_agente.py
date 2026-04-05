import os, django, json, time
from datetime import datetime, timedelta

# 1. Configurar entorno Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'quant_deriv_bot.settings'
# Añadir el path del proyecto para importar modelos
import sys
sys.path.append('/var/www/intradia.com.co')
django.setup()

from gestion_riesgo.models import OperacionBinance, TickBinance

CONFIG_PATH = "/var/www/intradia.com.co/bot_config.json"
LOG_PATH = "/var/www/intradia.com.co/ajuste_dinamico.log"
STATUS_JSON = "/tmp/bot_binance_status.json"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(msg)

def relax_filters():
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
        
        cambios = []
        
        # Relajar ADX (mínimo 20.0)
        if config["ADX_MIN"] > 20.0:
            old = config["ADX_MIN"]
            config["ADX_MIN"] = round(max(15.0, config["ADX_MIN"] - 1.0), 1)
            cambios.append(f"ADX: {old}->{config['ADX_MIN']}")

        # Relajar EMA GAP (mínimo 0.04)
        if config["EMA_GAP_PCT"] > 0.04:
            old = config["EMA_GAP_PCT"]
            config["EMA_GAP_PCT"] = round(max(0.03, config["EMA_GAP_PCT"] - 0.005), 3)
            cambios.append(f"GAP: {old}->{config['EMA_GAP_PCT']}")
            
        # Relajar Momentum (mínimo 0.02)
        if config["MOMENTUM_MIN_PCT"] > 0.02:
            old = config["MOMENTUM_MIN_PCT"]
            config["MOMENTUM_MIN_PCT"] = round(max(0.015, config["MOMENTUM_MIN_PCT"] - 0.005), 3)
            cambios.append(f"MOM: {old}->{config['MOMENTUM_MIN_PCT']}")

        if cambios:
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
            log(f"🔓 Relajando filtros por inactividad: {', '.join(cambios)}")
            os.system("systemctl restart binance_bot.service")
            log("🔄 Bot reiniciado con nueva configuración.")
        else:
            log("ℹ️ Filtros ya están en el nivel mínimo de seguridad. Esperando mercado.")
            
    except Exception as e:
        log(f"❌ Error relajando filtros: {e}")

def run_diagnostic():
    log("🧐 Iniciando diagnóstico de inactividad...")
    
    # 1. Verificar si hubo trades en las últimas 2 horas
    hace_2h = datetime.now() - timedelta(hours=2)
    ops_recientes = OperacionBinance.objects.filter(created_at__gte=hace_2h).count()
    
    if ops_recientes > 0:
        log(f"✅ Se detectaron {ops_recientes} operaciones en las últimas 2h. No se requiere ajuste.")
        return

    log("⚠️ No hubo trades en las últimas 2h. Analizando causa técnica...")

    # 2. Verificar si el bot está recibiendo ticks (¿está vivo?)
    hace_2min = datetime.now() - timedelta(minutes=2)
    ticks_recientes = TickBinance.objects.filter(timestamp__gte=hace_2min).count()
    
    if ticks_recientes == 0:
        log("🚨 CRÍTICO: El bot NO está registrando ticks. Posible caída de conexión. Reiniciando...")
        os.system("systemctl restart binance_bot.service")
        return

    # 3. Leer por qué el bot está rechazando (del archivo temporal)
    razon_dominante = "desconocida"
    try:
        if os.path.exists(STATUS_JSON):
            with open(STATUS_JSON, "r") as f:
                status = json.load(f)
                msg = status.get("status", "").lower()
                if "adx_bajo" in msg: razon_dominante = "ADX bajo"
                elif "gap_bajo" in msg: razon_dominante = "EMA GAP bajo"
                log(f"🔍 Causa detectada en tiempo real: {msg}")
    except:
        pass

    # 4. Decisión: Si el bot está vivo pero no opera, relajar filtros
    log(f"📉 Mercado lento o filtros muy estrictos ({razon_dominante}).")
    relax_filters()

if __name__ == "__main__":
    run_diagnostic()
