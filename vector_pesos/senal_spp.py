from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Optional

from django.conf import settings

from vector_pesos.filtro_rsi_zona import FiltroRSIZona, ResultadoFiltroRSI


@dataclass
class TendenciaState:
    highs: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    lows: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    trs: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    plus_dm: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    minus_dm: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    adx: float = 0.0
    atr: float = 0.0
    prev_high: float | None = None
    prev_low: float | None = None
    prev_close: float | None = None


def _calc_true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return high - low
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close)
    )


def _calc_dm(high: float, low: float, prev_high: float | None, prev_low: float | None) -> tuple[float, float]:
    if prev_high is None or prev_low is None:
        return 0.0, 0.0
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
    minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0
    return plus_dm, minus_dm


def calcular_adx_atr(
    precio: float,
    estado_tendencia: TendenciaState,
    adx_period: int = 14,
    atr_period: int = 14,
) -> tuple[float, float]:
    high = precio
    low = precio
    
    if len(estado_tendencia.highs) > 0:
        high = max(estado_tendencia.highs[-1], precio)
        low = min(estado_tendencia.lows[-1], precio)
    
    estado_tendencia.highs.append(high)
    estado_tendencia.lows.append(low)
    
    tr = _calc_true_range(high, low, estado_tendencia.prev_close)
    plus_dm, minus_dm = _calc_dm(high, low, estado_tendencia.prev_high, estado_tendencia.prev_low)
    
    estado_tendencia.trs.append(tr)
    estado_tendencia.plus_dm.append(plus_dm)
    estado_tendencia.minus_dm.append(minus_dm)
    
    estado_tendencia.prev_high = high
    estado_tendencia.prev_low = low
    estado_tendencia.prev_close = precio
    
    if len(estado_tendencia.trs) < adx_period + 1:
        return 0.0, 0.0
    
    tr_avg = sum(list(estado_tendencia.trs)[-adx_period:]) / adx_period
    plus_dm_avg = sum(list(estado_tendencia.plus_dm)[-adx_period:]) / adx_period
    minus_dm_avg = sum(list(estado_tendencia.minus_dm)[-adx_period:]) / adx_period
    
    if tr_avg == 0:
        return 0.0, 0.0
    
    plus_di = (plus_dm_avg / tr_avg) * 100
    minus_di = (minus_dm_avg / tr_avg) * 100
    
    if plus_di + minus_di == 0:
        return 0.0, tr_avg
    
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    
    alpha = 2.0 / (adx_period + 1)
    adx = (alpha * dx) + ((1.0 - alpha) * estado_tendencia.adx) if estado_tendencia.adx > 0 else dx
    estado_tendencia.adx = adx
    
    atr = tr_avg
    
    return adx, atr


def _es_rango_lateral(precios: Deque[float], ventana: int = 50, threshold_mult: float = 0.0001) -> bool:
    if len(precios) < ventana:
        return False
    
    arr = list(precios)[-ventana:]
    precio_actual = arr[-1]
    rango = max(arr) - min(arr)
    
    if precio_actual == 0:
        return False
    
    rango_pct = rango / precio_actual
    return rango_pct < threshold_mult


@dataclass(frozen=True)
class ResultadoSenalSPP:
    """
    Resultado de la estrategia: estructura + pendiente + pullback (ticks o minutos para forex).
    """

    decision: str  # "COMPRA" | "VENTA" | "NO_OPERAR"
    razon: str
    duracion_ticks: int | None = None
    duracion_unit: str = "t"  # "t" para ticks, "m" para minutos


@dataclass
class EstadoSPP:
    # EMAs incrementales (estables, no recalculan pasado)
    ema_fast: float | None = None
    ema_slow: float | None = None

    # Historial para pendientes
    ema_fast_hist: Deque[float] = None  # type: ignore[assignment]
    ema_slow_hist: Deque[float] = None  # type: ignore[assignment]

    # Precios / deltas para estructura y chop
    precios: Deque[float] = None  # type: ignore[assignment]
    deltas_sign: Deque[int] = None  # type: ignore[assignment]

    # Tendencia state (ADX/ATR)
    tendencia_state: TendenciaState = field(default_factory=TendenciaState)

    # Pullback state
    pb_activo: bool = False
    pb_len: int = 0
    pb_toco_fast: bool = False
    pb_dir: str | None = None  # "CALL" | "PUT"

    # Cooldown (ticks)
    cooldown_restante: int = 0

    # Fatigue tracking
    racha_perdidas: int = 0
    ultima_resultado: str | None = None  # "ganancia" | "perdida"

    # Para logs "no saturar"
    last_razon: str | None = None

    # Filtro RSI-Zona
    filtro_rsi: FiltroRSIZona = field(default_factory=FiltroRSIZona)

    def __post_init__(self) -> None:
        if self.ema_fast_hist is None:
            self.ema_fast_hist = deque(maxlen=64)
        if self.ema_slow_hist is None:
            self.ema_slow_hist = deque(maxlen=64)
        if self.precios is None:
            self.precios = deque(maxlen=240)
        if self.deltas_sign is None:
            self.deltas_sign = deque(maxlen=64)


def _alpha(periodo: int) -> float:
    p = max(1, int(periodo))
    return 2.0 / (p + 1.0)


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _slope(hist: Deque[float], n: int) -> float | None:
    n = max(1, int(n))
    if len(hist) < (n + 1):
        return None
    return float(hist[-1] - hist[-(n + 1)])


def _choppy(deltas_sign: Deque[int], *, ventana: int, max_flips: int) -> bool:
    v = max(3, int(ventana))
    if len(deltas_sign) < v:
        return False
    seq = list(deltas_sign)[-v:]
    flips = 0
    prev = 0
    for s in seq:
        if s == 0:
            continue
        if prev != 0 and s != prev:
            flips += 1
        prev = s
    return flips >= int(max_flips)


def _swing_lows(prices: list[float]) -> list[float]:
    lows: list[float] = []
    # Muy simple: mínimo local (p[i] < p[i-1] y p[i] < p[i+1])
    for i in range(1, len(prices) - 1):
        if prices[i] < prices[i - 1] and prices[i] < prices[i + 1]:
            lows.append(float(prices[i]))
    return lows


def _swing_highs(prices: list[float]) -> list[float]:
    highs: list[float] = []
    for i in range(1, len(prices) - 1):
        if prices[i] > prices[i - 1] and prices[i] > prices[i + 1]:
            highs.append(float(prices[i]))
    return highs


def _estructura_ok(
    prices: Deque[float],
    *,
    direccion: str,  # "CALL" | "PUT"
    ventana: int,
    min_delta: float,
) -> bool:
    w = max(8, int(ventana))
    if len(prices) < w:
        return False
    arr = list(prices)[-w:]
    if direccion == "CALL":
        lows = _swing_lows(arr)
        if len(lows) < 2:
            return False
        return (lows[-1] - lows[-2]) >= float(min_delta)
    highs = _swing_highs(arr)
    if len(highs) < 2:
        return False
    return (highs[-2] - highs[-1]) >= float(min_delta)  # lower highs


def _duracion_por_slope(symbol: str, *, slope_abs: float, slope_threshold: float) -> int:
    """
    Duración recomendada (ticks) según fuerza del impulso.
    MODIFICADO: Usar siempre 10 ticks para mayor probabilidad de éxito.
    """
    # Siempre retornar 10 ticks (máximo) para mayor chance de acierto
    return 10
    if strength >= 1.5:
        return 10
    return 10


def evaluar_senal_spp(
    *,
    symbol: str,
    precio: float,
    estado: EstadoSPP,
    # EMA periods - configurables para forex (EMA 9/21 - más reactiva)
    ema_fast_period: int = getattr(settings, "SP_EMA_FAST", 9),
    ema_slow_period: int = getattr(settings, "SP_EMA_SLOW", 21),
) -> ResultadoSenalSPP:
    """
    Estrategia de CONTINUACIÓN DE TENDENCIA para FOREX.
    Usa EMA20/EMA50 para más reactividad en forex.
    
    Reglas:
    1. EMA20 > EMA50 = tendencia ALCISTA (CALL)
    2. EMA20 < EMA50 = tendencia BAJISTA (PUT)
    3. Precio hace pullback hacia EMA50 y rebota
    4. Entrar cuando precio rompe el máximo/mínimo reciente
    """
    # ===== CONFIG =====
    slope_n = int(getattr(settings, "SPP_SLOPE_N", 5) or 5)
    cooldown_ticks = int(getattr(settings, "SPP_COOLDOWN_TICKS", 80) or 80)
    dynamic_cooldown = getattr(settings, "SPP_DYNAMIC_COOLDOWN", True)
    fatiga_perdidas = int(getattr(settings, "SPP_FATIGA_PRDIDAS", 3) or 3)
    fatiga_multiplicador = float(getattr(settings, "SPP_FATIGA_MULTIPLICADOR", 1.5) or 1.5)
    choppy_window = int(getattr(settings, "SPP_CHOPPY_WINDOW", 20) or 20)
    choppy_max_flips = int(getattr(settings, "SPP_CHOPPY_MAX_FLIPS", 12) or 12)

    # Thresholds específicos para forex (ajustados para EMA 9/21 más reactiva)
    slope_threshold = float(getattr(settings, "SPP_SLOPE_THRESHOLD_FOREX", 0.00001) or 0.00001)
    min_ema_gap = float(getattr(settings, "SPP_MIN_EMA_GAP_FOREX", 0.00003) or 0.00003)

    # Filtros de tendencia (ADX/ATR)
    adx_enabled = getattr(settings, "ADX_ENABLED", False)
    adx_threshold = float(getattr(settings, "ADX_THRESHOLD", 25) or 25)
    atr_volatility_filter = getattr(settings, "ATR_VOLATILITY_FILTER", False)
    atr_low_threshold = float(getattr(settings, "ATR_LOW_THRESHOLD", 0.00005) or 0.00005)
    atr_high_threshold = float(getattr(settings, "ATR_HIGH_THRESHOLD", 0.0005) or 0.0005)

    # ===== UPDATE PRICE/DELTA =====
    precio = float(precio)
    prev = estado.precios[-1] if len(estado.precios) else None
    estado.precios.append(precio)
    if prev is not None:
        estado.deltas_sign.append(_sign(precio - float(prev)))

    # ===== CALCULAR ADX Y ATR =====
    adx, atr = calcular_adx_atr(precio, estado.tendencia_state)

    # ===== COOLDOWN =====
    if estado.cooldown_restante > 0:
        estado.cooldown_restante -= 1
        return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"cooldown({estado.cooldown_restante})")

    # ===== UPDATE EMAs (incremental) =====
    if estado.ema_fast is None or estado.ema_slow is None:
        estado.ema_fast = precio
        estado.ema_slow = precio
    else:
        af = _alpha(ema_fast_period)
        as_ = _alpha(ema_slow_period)
        estado.ema_fast = (af * precio) + ((1.0 - af) * float(estado.ema_fast))
        estado.ema_slow = (as_ * precio) + ((1.0 - as_) * float(estado.ema_slow))

    estado.ema_fast_hist.append(float(estado.ema_fast))
    estado.ema_slow_hist.append(float(estado.ema_slow))

    # ===== DETERMINAR TENDENCIA =====
    ema_fast = float(estado.ema_fast)
    ema_slow = float(estado.ema_slow)
    
    # Determinar bias basado en posición de EMAs
    if ema_fast > ema_slow:
        bias = "CALL"
    elif ema_fast < ema_slow:
        bias = "PUT"
    else:
        # Si EMAs iguales, usar pendiente del precio
        if len(estado.precios) >= 2:
            precio_actual = estado.precios[-1]
            precio_anterior = estado.precios[-2]
            if precio_actual > precio_anterior:
                bias = "CALL"
            elif precio_actual < precio_anterior:
                bias = "PUT"
            else:
                return ResultadoSenalSPP(decision="NO_OPERAR", razon="mercado_lateral")
        else:
            return ResultadoSenalSPP(decision="NO_OPERAR", razon="warmup")

    # ===== FILTRO CHOPPY: evitar mercados laterales =====
    if _choppy(estado.deltas_sign, ventana=choppy_window, max_flips=choppy_max_flips):
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="mercado_choppy")

    # ===== FILTRO ADX: solo operar si hay tendencia definida =====
    if adx_enabled and adx > 0 and adx < adx_threshold:
        return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"adx_debil({adx:.1f}<{adx_threshold})")

    # ===== FILTRO ATR: evitar volatilidad muy baja o muy alta =====
    if atr_volatility_filter and atr > 0:
        if atr < atr_low_threshold:
            return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"atr_bajo({atr:.6f})")
        if atr > atr_high_threshold:
            return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"atr_alto({atr:.6f})")
    
    # ===== FILTRO RANGO LATERAL: evitar precio en rango =====
    if _es_rango_lateral(estado.precios, ventana=50, threshold_mult=0.002):
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="rango_lateral")
    
    # ===== SEÑAL DE CONTINUACIÓN DE TENDENCIA =====
    # Calcular cooldown dinámico basado en resultado anterior y fatiga
    cooldown_aplicado = cooldown_ticks
    
    if dynamic_cooldown and estado.ultima_resultado == "perdida":
        cooldown_aplicado = int(cooldown_ticks * fatiga_multiplicador)
    
    if estado.racha_perdidas >= fatiga_perdidas:
        cooldown_aplicado = int(cooldown_aplicado * fatiga_multiplicador)
    
    # Operar en la dirección de la tendencia (EMA crossover o precio)
    # Determinar duración basada en el símbolo
    if symbol.startswith("frx"):
        dur = 5  # 5 minutos para forex
    else:
        dur = 5  # 5 ticks para índices
    
    if bias == "CALL":
        senal_ema = "COMPRA"
        razon_ema = "tendencia_alcista"
    else:
        senal_ema = "VENTA"
        razon_ema = "tendencia_bajista"
    
    # ===== FILTRO RSI-ZONA (SECUNDARIO) =====
    resultado_rsi = estado.filtro_rsi.actualizar(precio, ema_fast, ema_slow, bias)
    
    if resultado_rsi.decision == "INVALIDAR":
        estado.cooldown_restante = cooldown_aplicado
        return ResultadoSenalSPP(decision="NO_OPERAR", razon=resultado_rsi.razon)
    
    # Determinar unidad de duración
    duracion_unit = "m" if symbol.startswith("frx") else "t"
    
    if resultado_rsi.decision == "CONFIRMAR":
        estado.cooldown_restante = cooldown_aplicado
        return ResultadoSenalSPP(
            decision=senal_ema, 
            razon=f"{razon_ema}_{resultado_rsi.razon}", 
            duracion_ticks=int(dur),
            duracion_unit=duracion_unit
        )
    
    # NEUTRAL: usar señal original
    estado.cooldown_restante = cooldown_aplicado
    return ResultadoSenalSPP(
        decision=senal_ema, 
        razon=razon_ema, 
        duracion_ticks=int(dur),
        duracion_unit=duracion_unit
    )


def reportar_resultado_spp(estado: EstadoSPP, fue_ganancia: bool) -> None:
    """
    Actualiza el tracking de fatiga basado en el resultado de la última operación.
    Debe llamarse después de cerrar una operación.
    """
    if fue_ganancia:
        estado.ultima_resultado = "ganancia"
        estado.racha_perdidas = 0
    else:
        estado.ultima_resultado = "perdida"
        estado.racha_perdidas += 1

