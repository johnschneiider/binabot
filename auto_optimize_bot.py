import os, django, json
from decimal import Decimal
from datetime import datetime, timedelta

# Configurar Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'quant_deriv_bot.settings'
django.setup()

from gestion_riesgo.models import OperacionBinance

CONFIG_PATH = "/var/www/intradia.com.co/bot_config.json"
LOG_OPTIMIZE = "/var/www/intradia.com.co/optimize.log"

def log(msg):
    with open(LOG_OPTIMIZE, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    print(msg)

def optimize():
    # 1. Cargar config actual
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    # 2. Analizar ultimas 50 operaciones
    ops = list(OperacionBinance.objects.order_by('-created_at')[:50])
    if not ops:
        log("No hay operaciones para analizar.")
        return

    wins = sum(1 for o in ops if o.es_win)
    total = len(ops)
    wr = (wins / total * 100) if total > 0 else 0
    
    log(f"Analizando {total} ops. Winrate actual: {wr:.1f}%")

    # 3. Lógica de ajuste
    cambios = False
    
    if wr < 70 and total >= 10:
        log("Winrate < 70%. Apretando filtros para mayor precisión...")
        
        # Aumentar ADX mínimo (máx 35)
        if config["ADX_MIN"] < 35:
            config["ADX_MIN"] = round(config["ADX_MIN"] + 1.0, 1)
            cambios = True
            
        # Aumentar Gap EMA (máx 0.15)
        if config["EMA_GAP_PCT"] < 0.15:
            config["EMA_GAP_PCT"] = round(config["EMA_GAP_PCT"] + 0.01, 3)
            cambios = True
            
        # Aumentar Momentum necesario (máx 0.08)
        if config["MOMENTUM_MIN_PCT"] < 0.08:
            config["MOMENTUM_MIN_PCT"] = round(config["MOMENTUM_MIN_PCT"] + 0.005, 3)
            cambios = True

        # Ser más estricto con RSI (apretar 1 punto)
        if config["RSI_CALL_MAX"] > 60:
            config["RSI_CALL_MAX"] -= 1
            cambios = True
        if config["RSI_PUT_MIN"] < 40:
            config["RSI_PUT_MIN"] += 1
            cambios = True

    elif wr > 85 and total >= 20:
        log("Winrate > 85%. El bot es muy preciso, relajando ligeramente para captar más señales...")
        
        # Relajar ADX (mín 22)
        if config["ADX_MIN"] > 22:
            config["ADX_MIN"] = round(config["ADX_MIN"] - 0.5, 1)
            cambios = True
            
        # Relajar Gap EMA (mín 0.05)
        if config["EMA_GAP_PCT"] > 0.05:
            config["EMA_GAP_PCT"] = round(config["EMA_GAP_PCT"] - 0.005, 3)
            cambios = True

    # 4. Guardar y reiniciar si hubo cambios
    if cambios:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        log(f"Nueva config guardada: ADX_MIN={config['ADX_MIN']}, EMA_GAP={config['EMA_GAP_PCT']}, RSI={config['RSI_CALL_MAX']}/{config['RSI_PUT_MIN']}")
        
        # Reiniciar el servicio del bot para aplicar cambios
        os.system("systemctl restart binance_bot")
        log("Servicio binance_bot reiniciado.")
    else:
        log("No se requieren cambios en la configuración.")

if __name__ == "__main__":
    optimize()
