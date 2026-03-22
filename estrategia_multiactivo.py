"""
Estrategia Multi-Activo Adaptativa para Deriv
Combina: Volatility 75, R_100, Boom/Crash 500
Basada en investigación de estrategias exitosas 2026
"""

from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional, Dict, List
import statistics
import math

@dataclass
class EstadoMultiActivo:
    """Estado para estrategia multi-activo"""
    precios: Dict[str, Deque[float]] = None
    retornos: Dict[str, Deque[float]] = None
    volatilidades: Dict[str, float] = None
    tendencias: Dict[str, float] = None
    momentum: Dict[str, float] = None
    rsi: Dict[str, float] = None
    ema_rapida: Dict[str, Optional[float]] = None
    ema_lenta: Dict[str, Optional[float]] = None
    soportes: Dict[str, Deque[float]] = None
    resistencias: Dict[str, Deque[float]] = None
    ultimo_trade: Dict[str, int] = None
    racha_perdidas: Dict[str, int] = None
    capital_por_activo: Dict[str, float] = None
    
    def __post_init__(self):
        if self.precios is None:
            self.precios = {}
        if self.retornos is None:
            self.retornos = {}
        if self.volatilidades is None:
            self.volatilidades = {}
        if self.tendencias is None:
            self.tendencias = {}
        if self.momentum is None:
            self.momentum = {}
        if self.rsi is None:
            self.rsi = {}
        if self.ema_rapida is None:
            self.ema_rapida = {}
        if self.ema_lenta is None:
            self.ema_lenta = {}
        if self.soportes is None:
            self.soportes = {}
        if self.resistencias is None:
            self.resistencias = {}
        if self.ultimo_trade is None:
            self.ultimo_trade = {}
        if self.racha_perdidas is None:
            self.racha_perdidas = {}
        if self.capital_por_activo is None:
            self.capital_por_activo = {}
    
    def inicializar_activo(self, symbol: str):
        """Inicializa estado para un activo nuevo"""
        if symbol not in self.precios:
            self.precios[symbol] = deque(maxlen=200)
            self.retornos[symbol] = deque(maxlen=100)
            self.volatilidades[symbol] = 0.0
            self.tendencias[symbol] = 0.0
            self.momentum[symbol] = 0.0
            self.rsi[symbol] = 50.0
            self.ema_rapida[symbol] = None
            self.ema_lenta[symbol] = None
            self.soportes[symbol] = deque(maxlen=20)
            self.resistencias[symbol] = deque(maxlen=20)
            self.ultimo_trade[symbol] = 0
            self.racha_perdidas[symbol] = 0
            self.capital_por_activo[symbol] = 0.0

def calcular_rsi_preciso(precios: Deque[float], periodo: int = 14) -> float:
    """Calcula RSI con mayor precisión"""
    if len(precios) < periodo + 1:
        return 50.0
    
    gains = []
    losses = []
    
    for i in range(1, len(precios)):
        cambio = precios[i] - precios[i-1]
        if cambio > 0:
            gains.append(cambio)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(cambio))
    
    avg_gain = sum(gains[-periodo:]) / periodo
    avg_loss = sum(losses[-periodo:]) / periodo
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def detectar_soporte_resistencia(precios: Deque[float], ventana: int = 50) -> tuple[float, float]:
    """Detecta niveles de soporte y resistencia"""
    if len(precios) < ventana:
        return None, None
    
    precios_list = list(precios)[-ventana:]
    
    # Soporte: mínimos locales
    soportes = []
    for i in range(2, len(precios_list) - 2):
        if precios_list[i] < precios_list[i-1] and precios_list[i] < precios_list[i+1]:
            soportes.append(precios_list[i])
    
    # Resistencia: máximos locales
    resistencias = []
    for i in range(2, len(precios_list) - 2):
        if precios_list[i] > precios_list[i-1] and precios_list[i] > precios_list[i+1]:
            resistencias.append(precios_list[i])
    
    soporte = max(soportes) if soportes else min(precios_list)
    resistencia = min(resistencias) if resistencias else max(precios_list)
    
    return soporte, resistencia

def calcular_fuerza_tendencia(precios: Deque[float], ema_fast: int = 9, ema_slow: int = 21) -> float:
    """Calcula fuerza de tendencia normalizada"""
    if len(precios) < ema_slow + 1:
        return 0.0
    
    # Calcular EMAs
    alpha_fast = 2.0 / (ema_fast + 1)
    alpha_slow = 2.0 / (ema_slow + 1)
    
    ema_f = precios[0]
    ema_s = precios[0]
    
    for precio in precios:
        ema_f = alpha_fast * precio + (1 - alpha_fast) * ema_f
        ema_s = alpha_slow * precio + (1 - alpha_slow) * ema_s
    
    # Normalizar gap por precio
    gap = (ema_f - ema_s) / ema_s
    
    return gap

def evaluar_multi_activo(
    symbol: str,
    precio: float,
    estado: EstadoMultiActivo,
    *,
    config: dict = None
) -> dict:
    """
    Evalúa señal para un activo específico
    """
    # Configuración por defecto
    if config is None:
        config = {
            'ema_fast': 9,
            'ema_slow': 21,
            'rsi_periodo': 14,
            'rsi_sobrecompra': 70,
            'rsi_sobreventa': 30,
            'momentum_periodo': 10,
            'volatilidad_periodo': 20,
            'cooldown_minimo': 3,
            'umbral_fuerza_tendencia': 0.0001,
            'umbral_volatilidad_min': 0.00005,
            'stake_base': 1.0,
            'max_stake': 2.0
        }
    
    # Inicializar activo si es nuevo
    estado.inicializar_activo(symbol)
    
    # Actualizar datos
    estado.precios[symbol].append(precio)
    
    if len(estado.precios[symbol]) < config['rsi_periodo'] + 10:
        return {
            "decision": "NO_OPERAR",
            "razon": "warmup",
            "stake": 0.0,
            "contract_type": None,
            "confidence": 0.0
        }
    
    # Calcular indicadores
    rsi = calcular_rsi_preciso(estado.precios[symbol], config['rsi_periodo'])
    estado.rsi[symbol] = rsi
    
    # Calcular volatilidad
    if len(estado.precios[symbol]) >= config['volatilidad_periodo']:
        retornos = []
        precios_list = list(estado.precios[symbol])
        for i in range(1, min(config['volatilidad_periodo'], len(precios_list))):
            if precios_list[-i-1] != 0:
                ret = (precios_list[-i] - precios_list[-i-1]) / precios_list[-i-1]
                retornos.append(ret)
        
        if retornos:
            estado.volatilidades[symbol] = statistics.stdev(retornos) if len(retornos) > 1 else 0.0
    
    # Calcular momentum
    if len(estado.precios[symbol]) >= config['momentum_periodo'] + 1:
        precio_actual = precio
        precio_pasado = list(estado.precios[symbol])[-(config['momentum_periodo'] + 1)]
        if precio_pasado != 0:
            estado.momentum[symbol] = (precio_actual - precio_pasado) / precio_pasado
    
    # Calcular fuerza de tendencia
    fuerza_tendencia = calcular_fuerza_tendencia(
        estado.precios[symbol], 
        config['ema_fast'], 
        config['ema_slow']
    )
    estado.tendencias[symbol] = fuerza_tendencia
    
    # Detectar soporte/resistencia
    soporte, resistencia = detectar_soporte_resistencia(estado.precios[symbol])
    
    # Filtros
    razones_no_operar = []
    
    # 1. Filtro de cooldown
    ticks_desde_ultimo = len(estado.precios[symbol]) - estado.ultimo_trade[symbol]
    if ticks_desde_ultimo < config['cooldown_minimo']:
        razones_no_operar.append(f"cooldown({ticks_desde_ultimo}/{config['cooldown_minimo']})")
    
    # 2. Filtro de fatiga
    if estado.racha_perdidas[symbol] >= 3:
        razones_no_operar.append(f"fatiga({estado.racha_perdidas[symbol]})")
    
    # 3. Filtro de volatilidad muy baja
    if estado.volatilidades[symbol] < config['umbral_volatilidad_min']:
        razones_no_operar.append(f"volatilidad_baja({estado.volatilidades[symbol]:.6f})")
    
    # 4. Filtro de tendencia muy débil
    if abs(fuerza_tendencia) < config['umbral_fuerza_tendencia']:
        razones_no_operar.append(f"tendencia_debil({fuerza_tendencia:.6f})")
    
    # Determinar dirección
    tendencia_alcista = fuerza_tendencia > 0
    tendencia_bajista = fuerza_tendencia < 0
    
    # Señales de entrada
    senal = None
    contract_type = None
    razon = ""
    confidence = 0.0
    
    if not razones_no_operar:
        # Estrategia de soporte/resistencia + momentum
        if soporte and resistencia:
            precio_vs_soporte = (precio - soporte) / soporte if soporte else 0
            precio_vs_resistencia = (precio - resistencia) / resistencia if resistencia else 0
            
            # CALL: cerca de soporte + tendencia alcista + RSI sobreventa
            if (tendencia_alcista and 
                rsi < config['rsi_sobreventa'] and 
                precio_vs_soporte < 0.001 and
                estado.momentum[symbol] > 0):
                
                senal = "COMPRA"
                contract_type = "CALL"
                razon = f"soporte_rsi{rsi:.1f}_mom{estado.momentum[symbol]:.6f}"
                confidence = min(1.0, abs(precio_vs_soporte) * 1000)
            
            # PUT: cerca de resistencia + tendencia bajista + RSI sobrecompra
            elif (tendencia_bajista and 
                  rsi > config['rsi_sobrecompra'] and 
                  precio_vs_resistencia > -0.001 and
                  estado.momentum[symbol] < 0):
                
                senal = "VENTA"
                contract_type = "PUT"
                razon = f"resistencia_rsi{rsi:.1f}_mom{estado.momentum[symbol]:.6f}"
                confidence = min(1.0, abs(precio_vs_resistencia) * 1000)
    
    if razones_no_operar or senal is None:
        return {
            "decision": "NO_OPERAR",
            "razon": " | ".join(razones_no_operar) if razones_no_operar else "sin_senal",
            "stake": 0.0,
            "contract_type": None,
            "confidence": 0.0,
            "indicadores": {
                "rsi": rsi,
                "volatilidad": estado.volatilidades[symbol],
                "momentum": estado.momentum[symbol],
                "fuerza_tendencia": fuerza_tendencia,
                "soporte": soporte,
                "resistencia": resistencia
            }
        }
    
    # Calcular stake basado en confianza y volatilidad
    stake_base = config['stake_base']
    
    # Ajustar stake por volatilidad (menos stake en alta volatilidad)
    factor_volatilidad = 1.0 / (1.0 + estado.volatilidades[symbol] * 10000)
    stake = stake_base * confidence * factor_volatilidad
    stake = min(config['max_stake'], max(0.5, stake))
    
    # Actualizar estado
    estado.ultimo_trade[symbol] = len(estado.precios[symbol]) - 1
    
    return {
        "decision": senal,
        "razon": razon,
        "stake": round(stake, 2),
        "contract_type": contract_type,
        "confidence": round(confidence, 2),
        "indicadores": {
            "rsi": rsi,
            "volatilidad": estado.volatilidades[symbol],
            "momentum": estado.momentum[symbol],
            "fuerza_tendencia": fuerza_tendencia,
            "soporte": soporte,
            "resistencia": resistencia
        }
    }

def reportar_resulto_multi(estado: EstadoMultiActivo, symbol: str, fue_ganancia: bool):
    """Actualiza estado con resultado"""
    if fue_ganancia:
        estado.racha_perdidas[symbol] = 0
    else:
        estado.racha_perdidas[symbol] = estado.racha_perdidas.get(symbol, 0) + 1

# Configuraciones optimizadas por tipo de activo
CONFIGS_POR_ACTIVO = {
    # Volatility 75 - alta volatilidad, necesita parámetros más conservadores
    '1HZ75V': {
        'ema_fast': 9,
        'ema_slow': 21,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 75,
        'rsi_sobreventa': 25,
        'momentum_periodo': 15,
        'volatilidad_periodo': 30,
        'cooldown_minimo': 5,
        'umbral_fuerza_tendencia': 0.00005,
        'umbral_volatilidad_min': 0.0001,
        'stake_base': 0.5,
        'max_stake': 1.0
    },
    # R_100 - más estable
    'R_100': {
        'ema_fast': 9,
        'ema_slow': 21,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 70,
        'rsi_sobreventa': 30,
        'momentum_periodo': 10,
        'volatilidad_periodo': 20,
        'cooldown_minimo': 3,
        'umbral_fuerza_tendencia': 0.00002,
        'umbral_volatilidad_min': 0.00002,
        'stake_base': 1.0,
        'max_stake': 2.0
    },
    # Boom 500 - tendencias alcistas fuertes
    'Boom_500': {
        'ema_fast': 14,
        'ema_slow': 50,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 65,
        'rsi_sobreventa': 35,
        'momentum_periodo': 20,
        'volatilidad_periodo': 30,
        'cooldown_minimo': 5,
        'umbral_fuerza_tendencia': 0.00001,
        'umbral_volatilidad_min': 0.00003,
        'stake_base': 0.75,
        'max_stake': 1.5
    },
    # Crash 500 - tendencias bajistas fuertes
    'Crash_500': {
        'ema_fast': 14,
        'ema_slow': 50,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 65,
        'rsi_sobreventa': 35,
        'momentum_periodo': 20,
        'volatilidad_periodo': 30,
        'cooldown_minimo': 5,
        'umbral_fuerza_tendencia': 0.00001,
        'umbral_volatilidad_min': 0.00003,
        'stake_base': 0.75,
        'max_stake': 1.5
    },
    # R_10 - índice original
    'R_10': {
        'ema_fast': 9,
        'ema_slow': 21,
        'rsi_periodo': 14,
        'rsi_sobrecompra': 68,
        'rsi_sobreventa': 32,
        'momentum_periodo': 10,
        'volatilidad_periodo': 20,
        'cooldown_minimo': 3,
        'umbral_fuerza_tendencia': 0.00002,
        'umbral_volatilidad_min': 0.00002,
        'stake_base': 1.0,
        'max_stake': 2.0
    }
}