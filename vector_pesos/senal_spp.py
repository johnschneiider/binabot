from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional

from django.conf import settings


@dataclass(frozen=True)
class ResultadoSenalSPP:
    """
    Resultado de la estrategia: estructura + pendiente + pullback (ticks).
    """

    decision: str  # "COMPRA" | "VENTA" | "NO_OPERAR"
    razon: str
    duracion_ticks: int | None = None


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

    # Pullback state
    pb_activo: bool = False
    pb_len: int = 0
    pb_toco_fast: bool = False
    pb_dir: str | None = None  # "CALL" | "PUT"

    # Cooldown (ticks)
    cooldown_restante: int = 0

    # Para logs “no saturar”
    last_razon: str | None = None

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
    Evita 5 ticks; usa rangos 7–12 (R_10).

    Nota operativa:
    En la práctica, para el setup actual de Deriv (ticks), hemos observado validaciones
    que limitan la duración a 10 ticks en algunos offerings. Por eso, para R_100
    esta función nunca retornará > 10.
    """
    thr = max(1e-9, float(slope_threshold))
    strength = float(slope_abs) / thr
    if symbol == "R_10":
        if strength >= 2.5:
            return 7
        if strength >= 2.0:
            return 8
        if strength >= 1.5:
            return 9
        return 11
    # R_100
    # Max 10 por compatibilidad con offerings (ver OfferingsValidationError duration).
    # Mantenerlo simple: el backend ya clampa a 1..10, pero aquí evitamos que "piense" >10.
    if strength >= 2.5:
        return 10
    if strength >= 2.0:
        return 10
    if strength >= 1.5:
        return 10
    return 10


def evaluar_senal_spp(
    *,
    symbol: str,
    precio: float,
    estado: EstadoSPP,
    # EMA periods (FIJOS por requerimiento)
    ema_fast_period: int = 50,
    ema_slow_period: int = 100,
) -> ResultadoSenalSPP:
    """
    Estrategia: tendencia (EMA50 vs EMA100) + pendiente EMA50 + pullback + estructura.
    """
    # ===== CONFIG (settings, con defaults razonables) =====
    slope_n = int(getattr(settings, "SPP_SLOPE_N", 7) or 7)
    # Defaults más conservadores ("modo banco"): menos trades, más calidad.
    pullback_min = int(getattr(settings, "SPP_PULLBACK_MIN_TICKS", 4) or 4)
    pullback_max = int(getattr(settings, "SPP_PULLBACK_MAX_TICKS", 7) or 7)
    pullback_dist_factor = float(getattr(settings, "SPP_PULLBACK_DIST_FACTOR", 0.45) or 0.45)
    cooldown_ticks = int(getattr(settings, "SPP_COOLDOWN_TICKS", 40) or 40)
    choppy_window = int(getattr(settings, "SPP_CHOPPY_WINDOW", 20) or 20)
    choppy_max_flips = int(getattr(settings, "SPP_CHOPPY_MAX_FLIPS", 10) or 10)
    estructura_window = int(getattr(settings, "SPP_ESTRUCTURA_WINDOW", 24) or 24)

    # thresholds por símbolo
    if symbol == "R_10":
        slope_threshold = float(getattr(settings, "SPP_SLOPE_THRESHOLD_R10", 0.04) or 0.04)
        min_ema_gap = float(getattr(settings, "SPP_MIN_EMA_GAP_R10", 0.08) or 0.08)
        slow_eps = float(getattr(settings, "SPP_SLOW_SLOPE_EPS_R10", 0.0) or 0.0)
        estructura_min_delta = float(getattr(settings, "SPP_ESTRUCTURA_MIN_DELTA_R10", 0.03) or 0.03)
        retake_min_delta = float(getattr(settings, "SPP_RETAKE_MIN_DELTA_R10", 0.015) or 0.015)
    else:
        slope_threshold = float(getattr(settings, "SPP_SLOPE_THRESHOLD_R100", 0.18) or 0.18)
        min_ema_gap = float(getattr(settings, "SPP_MIN_EMA_GAP_R100", 0.35) or 0.35)
        slow_eps = float(getattr(settings, "SPP_SLOW_SLOPE_EPS_R100", 0.0) or 0.0)
        estructura_min_delta = float(getattr(settings, "SPP_ESTRUCTURA_MIN_DELTA_R100", 0.15) or 0.15)
        retake_min_delta = float(getattr(settings, "SPP_RETAKE_MIN_DELTA_R100", 0.06) or 0.06)

    # ===== UPDATE PRICE/DELTA =====
    precio = float(precio)
    prev = estado.precios[-1] if len(estado.precios) else None
    estado.precios.append(precio)
    if prev is not None:
        estado.deltas_sign.append(_sign(precio - float(prev)))

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

    # ===== FILTRO DURO: tendencia + compresión =====
    ema_fast = float(estado.ema_fast)
    ema_slow = float(estado.ema_slow)
    ema_gap = abs(ema_fast - ema_slow)
    if ema_gap < float(min_ema_gap):
        estado.pb_activo = False
        estado.pb_len = 0
        estado.pb_toco_fast = False
        return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"gap_pequeno({ema_gap:.4f}<{min_ema_gap:.4f})")

    if ema_fast > ema_slow:
        bias = "CALL"
    elif ema_fast < ema_slow:
        bias = "PUT"
    else:
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="sin_tendencia(emas_iguales)")

    # ===== PENDIENTE EMA FAST =====
    s_fast = _slope(estado.ema_fast_hist, slope_n)
    if s_fast is None:
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="warmup_slope")

    if bias == "CALL":
        if float(s_fast) < float(slope_threshold):
            estado.pb_activo = False
            estado.pb_len = 0
            estado.pb_toco_fast = False
            return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"slope_bajo({float(s_fast):.4f}<{slope_threshold:.4f})")
    else:
        if float(s_fast) > -float(slope_threshold):
            estado.pb_activo = False
            estado.pb_len = 0
            estado.pb_toco_fast = False
            return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"slope_bajo({float(s_fast):.4f}>-{slope_threshold:.4f})")

    # ===== CONFIRMACIÓN EMA SLOW =====
    s_slow = _slope(estado.ema_slow_hist, slope_n)
    if s_slow is None:
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="warmup_slow")

    if bias == "CALL":
        if float(s_slow) < -float(slow_eps):
            return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"slow_contra({float(s_slow):.4f})")
    else:
        if float(s_slow) > float(slow_eps):
            return ResultadoSenalSPP(decision="NO_OPERAR", razon=f"slow_contra({float(s_slow):.4f})")

    # ===== FILTRO SERRUCHO (estructura/chop) =====
    if _choppy(estado.deltas_sign, ventana=choppy_window, max_flips=choppy_max_flips):
        estado.pb_activo = False
        estado.pb_len = 0
        estado.pb_toco_fast = False
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="choppy")

    if not _estructura_ok(
        estado.precios,
        direccion=bias,
        ventana=estructura_window,
        min_delta=estructura_min_delta,
    ):
        # No reseteamos pullback siempre; pero si está activo demasiado tiempo, lo cortamos.
        if estado.pb_activo and estado.pb_len > pullback_max:
            estado.pb_activo = False
            estado.pb_len = 0
            estado.pb_toco_fast = False
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="estructura_no_ok")

    # ===== PULLBACK =====
    # Condición de proximidad: |p-ema_fast| <= factor * |ema_fast-ema_slow|
    dist_p_fast = abs(precio - ema_fast)
    dist_fast_slow = max(1e-12, abs(ema_fast - ema_slow))
    cerca_fast = dist_p_fast <= (float(pullback_dist_factor) * dist_fast_slow)

    # Reglas: no cruzar EMA slow
    if bias == "CALL":
        if precio < ema_slow:
            estado.pb_activo = False
            estado.pb_len = 0
            estado.pb_toco_fast = False
            return ResultadoSenalSPP(decision="NO_OPERAR", razon="cruza_ema_slow")
    else:
        if precio > ema_slow:
            estado.pb_activo = False
            estado.pb_len = 0
            estado.pb_toco_fast = False
            return ResultadoSenalSPP(decision="NO_OPERAR", razon="cruza_ema_slow")

    # Determinar delta del último tick para “retoma tendencia”
    delta = 0.0 if prev is None else (precio - float(prev))

    # Iniciar/continuar pullback cuando el precio va contra la tendencia.
    contra = (delta < 0.0) if bias == "CALL" else (delta > 0.0)
    favor = (delta > 0.0) if bias == "CALL" else (delta < 0.0)

    if not estado.pb_activo:
        if contra:
            estado.pb_activo = True
            estado.pb_dir = bias
            estado.pb_len = 1
            estado.pb_toco_fast = bool(cerca_fast)
            return ResultadoSenalSPP(decision="NO_OPERAR", razon="pullback_iniciando")
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="sin_pullback")

    # Pullback activo
    estado.pb_len += 1
    if cerca_fast:
        estado.pb_toco_fast = True

    # Si el pullback se hace muy largo, lo descartamos.
    if estado.pb_len > pullback_max:
        estado.pb_activo = False
        estado.pb_len = 0
        estado.pb_toco_fast = False
        return ResultadoSenalSPP(decision="NO_OPERAR", razon="pullback_largo")

    # Disparador: primer tick a favor tras pullback, con pullback válido:
    # - duración mínima
    # - tocó EMA fast (proximidad)
    # - retoma con delta mínimo (evita "micro-retomas" que suelen fallar)
    # - reclaim de EMA fast (confirmación extra)
    if (
        favor
        and estado.pb_toco_fast
        and estado.pb_len >= pullback_min
        and abs(float(delta)) >= float(retake_min_delta)
        and ((precio >= ema_fast) if bias == "CALL" else (precio <= ema_fast))
    ):
        dur = _duracion_por_slope(symbol, slope_abs=abs(float(s_fast)), slope_threshold=slope_threshold)
        estado.pb_activo = False
        estado.pb_len = 0
        estado.pb_toco_fast = False
        # Entrar
        if bias == "CALL":
            estado.cooldown_restante = cooldown_ticks
            return ResultadoSenalSPP(decision="COMPRA", razon="entrada_pullback_ok", duracion_ticks=int(dur))
        estado.cooldown_restante = cooldown_ticks
        return ResultadoSenalSPP(decision="VENTA", razon="entrada_pullback_ok", duracion_ticks=int(dur))

    # Si el pullback cambia de tipo o el mercado deja de cumplir, se cancela.
    return ResultadoSenalSPP(decision="NO_OPERAR", razon="pullback_en_progreso")

