"""
BACKTEST BINANCE - ESTRATEGIA EMA CROSSOVER
Analiza la estrategia actual con datos historicos de Binance
"""

import json
import time
from datetime import datetime
from dataclasses import dataclass
import urllib.request

# ============================================================
#  CONFIGURACION DEL BACKTEST
# ============================================================

@dataclass
class ParametrosBacktest:
    """Parametros del backtest"""
    simbolo: str = "BTCUSDT"
    timeframe: str = "1m"  # 1 minuto
    dias_historia: int = 7  # 7 dias de historia
    stake: float = 1.0
    payout: float = 0.95
    duracion_operacion: int = 120  # 120 segundos
    
    # Parametros de la estrategia
    ema_rapida: int = 8
    ema_media: int = 21
    ema_lenta: int = 55
    rsi_periodo: int = 14
    rsi_max: float = 65.0  # Para CALL
    rsi_min: float = 35.0  # Para PUT
    cooldown: int = 15

@dataclass
class ResultadoBacktest:
    """Resultado del backtest"""
    total_ops: int
    wins: int
    losses: int
    winrate: float
    pnl_total: float
    profit_factor: float
    max_drawdown: float
    expectancia: float
    ops_por_dia: float
    simbolo: str
    timeframe: str

# ============================================================
#  INDICADORES
# ============================================================

def calcular_ema(precios: list, periodo: int) -> list:
    """Calcula EMA para una lista de precios"""
    if len(precios) < periodo:
        return [None] * len(precios)
    
    ema = [None] * (periodo - 1)
    sma = sum(precios[:periodo]) / periodo
    ema.append(sma)
    
    multiplier = 2.0 / (periodo + 1.0)
    for i in range(periodo, len(precios)):
        ema_val = (precios[i] - ema[-1]) * multiplier + ema[-1]
        ema.append(ema_val)
    
    return ema

def calcular_rsi(precios: list, periodo: int = 14) -> list:
    """Calcula RSI para una lista de precios"""
    if len(precios) < periodo + 1:
        return [50.0] * len(precios)
    
    rsi = [50.0] * periodo
    
    cambios = []
    for i in range(1, len(precios)):
        cambios.append(precios[i] - precios[i-1])
    
    for i in range(periodo, len(cambios) + 1):
        ventana = cambios[i-periodo:i]
        ganancias = [max(c, 0) for c in ventana]
        perdidas = [max(-c, 0) for c in ventana]
        
        avg_g = sum(ganancias) / periodo
        avg_p = sum(perdidas) / periodo
        
        if avg_p == 0:
            rsi.append(100.0)
        else:
            rs = avg_g / avg_p
            rsi_val = 100.0 - (100.0 / (1.0 + rs))
            rsi.append(rsi_val)
    
    return rsi

# ============================================================
#  OBTENER DATOS HISTORICOS
# ============================================================

def obtener_datos_binance(simbolo: str, timeframe: str, dias: int) -> list:
    """Obtiene datos historicos de Binance (publico)"""
    print(f"Descargando datos de {simbolo} - {timeframe} - {dias} dias...")
    
    end_time = int(time.time() * 1000)
    start_time = end_time - (dias * 24 * 60 * 60 * 1000)
    
    base_url = "https://api.binance.com/api/v3/klines"
    all_data = []
    current_start = start_time
    
    while current_start < end_time:
        url = f"{base_url}?symbol={simbolo}&interval={timeframe}&startTime={current_start}&limit=1000"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())
                
                if not data:
                    break
                
                all_data.extend(data)
                current_start = data[-1][0] + 1
                
                print(f"  Descargados {len(all_data)} velas...")
                time.sleep(0.1)
                
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    print(f"Total: {len(all_data)} velas")
    return all_data

# ============================================================
#  ESTRATEGIA EMA CROSSOVER
# ============================================================

class EstadoEstrategia:
    def __init__(self):
        self.precios = []
        self.ema_rapida = None
        self.ema_media = None
        self.ema_lenta = None
        self.rsi = 50.0
        self.cooldown = 0
        self.operacion_pendiente = None

def evaluar_senal_backtest(estado: EstadoEstrategia, precio: float, params: ParametrosBacktest) -> tuple:
    estado.precios.append(precio)
    if len(estado.precios) > 300:
        estado.precios = estado.precios[-300:]
    
    if estado.cooldown > 0:
        estado.cooldown -= 1
        return ("NEUTRAL", f"cd{estado.cooldown}", "media")
    
    if len(estado.precios) < params.ema_lenta + 10:
        return ("NEUTRAL", "warmup", "baja")
    
    emas_rapida = calcular_ema(estado.precios, params.ema_rapida)
    emas_media = calcular_ema(estado.precios, params.ema_media)
    emas_lenta = calcular_ema(estado.precios, params.ema_lenta)
    rsi_vals = calcular_rsi(estado.precios, params.rsi_periodo)
    
    ema_rapida = emas_rapida[-1]
    ema_media = emas_media[-1]
    ema_lenta = emas_lenta[-1]
    rsi = rsi_vals[-1]
    
    if ema_rapida is None or ema_media is None or ema_lenta is None:
        return ("NEUTRAL", "sin_emas", "baja")
    
    ema_rapida_above_media = ema_rapida > ema_media
    ema_rapida_below_media = ema_rapida < ema_media
    
    if ema_rapida_above_media and rsi < params.rsi_max:
        estado.cooldown = params.cooldown
        return ("CALL", "ema_crossover_up", "alta")
    
    if ema_rapida_below_media and rsi > params.rsi_min:
        estado.cooldown = params.cooldown
        return ("PUT", "ema_crossover_dn", "alta")
    
    return ("NEUTRAL", "sin_senal", "baja")

# ============================================================
#  EJECUTAR BACKTEST
# ============================================================

def ejecutar_backtest(params: ParametrosBacktest):
    datos = obtener_datos_binance(params.simbolo, params.timeframe, params.dias_historia)
    
    if len(datos) < 100:
        print("Datos insuficientes")
        return None, None
    
    precios = [float(d[4]) for d in datos]
    timestamps = [d[0] for d in datos]
    
    print(f"\nBacktest con {len(precios)} velas...")
    print(f"Periodo: {datetime.fromtimestamp(timestamps[0]/1000)} - {datetime.fromtimestamp(timestamps[-1]/1000)}")
    
    estado = EstadoEstrategia()
    operaciones = []
    capital = 100.0
    capital_max = 100.0
    drawdown_max = 0.0
    
    for i in range(len(precios)):
        precio = precios[i]
        timestamp = timestamps[i]
        
        if estado.operacion_pendiente is not None:
            op = estado.operacion_pendiente
            tiempo_transcurrido = timestamp - op['timestamp_entrada']
            
            if tiempo_transcurrido >= params.duracion_operacion * 1000:
                precio_salida = precio
                es_win = (op['direccion'] == 'CALL' and precio_salida > op['precio_entrada']) or \
                         (op['direccion'] == 'PUT' and precio_salida < op['precio_entrada'])
                
                profit = (params.stake * params.payout) if es_win else -params.stake
                capital += profit
                
                if capital > capital_max:
                    capital_max = capital
                drawdown_actual = (capital_max - capital) / capital_max
                drawdown_max = max(drawdown_max, drawdown_actual)
                
                operaciones.append({
                    'timestamp': timestamp,
                    'direccion': op['direccion'],
                    'precio_entrada': op['precio_entrada'],
                    'precio_salida': precio_salida,
                    'es_win': es_win,
                    'profit': profit,
                    'capital': capital
                })
                
                estado.operacion_pendiente = None
        
        if estado.operacion_pendiente is None:
            senal, razon, confianza = evaluar_senal_backtest(estado, precio, params)
            
            if senal in ['CALL', 'PUT']:
                estado.operacion_pendiente = {
                    'direccion': senal,
                    'precio_entrada': precio,
                    'timestamp_entrada': timestamp,
                    'razon': razon,
                    'confianza': confianza
                }
    
    total_ops = len(operaciones)
    if total_ops == 0:
        print("No hay operaciones")
        return None, None
    
    wins = sum(1 for op in operaciones if op['es_win'])
    losses = total_ops - wins
    winrate = (wins / total_ops) * 100
    pnl_total = capital - 100.0
    
    ganancias = sum(op['profit'] for op in operaciones if op['profit'] > 0)
    perdidas = abs(sum(op['profit'] for op in operaciones if op['profit'] < 0))
    profit_factor = ganancias / perdidas if perdidas > 0 else float('inf')
    
    expectancia = (winrate/100 * params.payout * params.stake) - ((100-winrate)/100 * params.stake)
    
    dias_reales = (timestamps[-1] - timestamps[0]) / (1000 * 60 * 60 * 24)
    ops_por_dia = total_ops / dias_reales if dias_reales > 0 else 0
    
    resultado = ResultadoBacktest(
        total_ops=total_ops,
        wins=wins,
        losses=losses,
        winrate=winrate,
        pnl_total=pnl_total,
        profit_factor=profit_factor,
        max_drawdown=drawdown_max * 100,
        expectancia=expectancia,
        ops_por_dia=ops_por_dia,
        simbolo=params.simbolo,
        timeframe=params.timeframe
    )
    
    return resultado, operaciones

# ============================================================
#  MOSTRAR RESULTADOS
# ============================================================

def mostrar_resultados(resultado: ResultadoBacktest, operaciones: list, params: ParametrosBacktest):
    print("\n" + "="*60)
    print(f"RESULTADOS BACKTEST - {resultado.simbolo} ({resultado.timeframe})")
    print("="*60)
    
    print(f"\nESTADISTICAS:")
    print(f"   Total ops: {resultado.total_ops}")
    print(f"   Wins: {resultado.wins}")
    print(f"   Losses: {resultado.losses}")
    print(f"   Win Rate: {resultado.winrate:.1f}%")
    print(f"   P&L: ${resultado.pnl_total:.2f}")
    print(f"   Profit Factor: {resultado.profit_factor:.2f}")
    print(f"   Max Drawdown: {resultado.max_drawdown:.1f}%")
    print(f"   Expectativa: ${resultado.expectancia:.3f}")
    print(f"   Ops/dia: {resultado.ops_por_dia:.1f}")
    
    print(f"\nPARAMETROS:")
    print(f"   EMA: {params.ema_rapida}/{params.ema_media}/{params.ema_lenta}")
    print(f"   RSI: {params.rsi_min}-{params.rsi_max}")
    
    print(f"\nEVALUACION:")
    if resultado.winrate >= 80:
        print("   EXCELENTE (>80%) - Listo para trading real")
    elif resultado.winrate >= 70:
        print("   BUENO (70-80%) - Considerar mejoras")
    elif resultado.winrate >= 60:
        print("   ACEPTABLE (60-70%) - Necesita optimizacion")
    else:
        print("   BAJO (<60%) - NO usar dinero real")
    
    print(f"\nULTIMAS 10 OPERACIONES:")
    for op in operaciones[-10:]:
        fecha = datetime.fromtimestamp(op['timestamp']/1000).strftime("%H:%M")
        resultado_op = "WIN" if op['es_win'] else "LOSS"
        signo = "+" if op['es_win'] else ""
        print(f"   [{signo}] {fecha} {op['direccion']:4} | ${op['precio_entrada']:.2f} -> ${op['precio_salida']:.2f} | {resultado_op} (${op['profit']:+.2f})")

# ============================================================
#  MAIN
# ============================================================

if __name__ == "__main__":
    import time
    
    print("BACKTEST BINANCE - ESTRATEGIA EMA CROSSOVER")
    print("="*60)
    
    params = ParametrosBacktest(
        simbolo="BTCUSDT",
        timeframe="1m",
        dias_historia=7,
        stake=1.0,
        payout=0.95,
        ema_rapida=8,
        ema_media=21,
        ema_lenta=55
    )
    
    resultado, operaciones = ejecutar_backtest(params)
    
    if resultado:
        mostrar_resultados(resultado, operaciones, params)
    else:
        print("No se pudo ejecutar el backtest")
