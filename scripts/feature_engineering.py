"""
FEATURE ENGINEERING — Sniper Pullback ML v1.0
Construye el DataFrame de features para entrenar el modelo ML.

Diseño sin lookahead: toda feature en timestamp t usa SOLO datos hasta t (inclusive).
El label usa close[t + DURACION_VELAS], por eso se descarta el final del dataset.

Uso:
    python scripts/feature_engineering.py
    -> genera data/features_ETHUSDT.parquet, data/features_BTCUSDT.parquet, etc.
"""

import os
import math
import numpy as np
import pandas as pd

# ─── parámetros estrategia (deben coincidir con el bot) ────────────────────────
DURACION_VELAS    = 15   # hold en velas 1m
ADX_MIN           = 28
RSI_PERIODO       = 14
EMA50_SLOPE_N     = 5
EMA50_SLOPE_MIN   = 0.03
RSI_PULLBACK_CALL = 42
RSI_PULLBACK_PUT  = 58
RSI_RESUME_CALL   = 50
RSI_RESUME_PUT    = 50
VOL_FILTER_RATIO  = 0.8
WARMUP_CANDLES    = 60   # más largo para asegurar todos los indicadores

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_DIR = DATA_DIR


# ══════════════════════════════════════════════════════════════════════════════
#  INDICADORES (vectorizados sobre Series)
# ══════════════════════════════════════════════════════════════════════════════

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs   = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    up   = high.diff()
    down = -low.diff()
    dm_p = np.where((up > down) & (up > 0), up, 0.0)
    dm_n = np.where((down > up) & (down > 0), down, 0.0)
    atr_ = atr(high, low, close, n)
    di_p = 100 * pd.Series(dm_p, index=close.index).ewm(alpha=1/n, adjust=False).mean() / atr_
    di_n = 100 * pd.Series(dm_n, index=close.index).ewm(alpha=1/n, adjust=False).mean() / atr_
    dx   = (100 * (di_p - di_n).abs() / (di_p + di_n).replace(0, np.nan))
    return dx.ewm(alpha=1/n, adjust=False).mean()


def macd_hist(s: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    m     = ema(s, fast) - ema(s, slow)
    sig   = ema(m, signal)
    return m - sig


def stoch_k(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    lo_n = low.rolling(n).min()
    hi_n = high.rolling(n).max()
    return 100 * (close - lo_n) / (hi_n - lo_n).replace(0, np.nan)


def cci(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20) -> pd.Series:
    tp   = (high + low + close) / 3
    sma  = tp.rolling(n).mean()
    mad  = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad.replace(0, np.nan))


def bb_width(s: pd.Series, n: int = 20) -> pd.Series:
    m  = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return (2 * 2 * sd) / m.replace(0, np.nan) * 100   # band-width %


def linreg_slope(s: pd.Series, n: int = 3) -> pd.Series:
    """Rolling linear regression slope normalizado por precio."""
    x = np.arange(n)
    def _slope(y):
        if np.any(np.isnan(y)):
            return np.nan
        return np.polyfit(x, y, 1)[0] / (y.mean() or 1)
    return s.rolling(n).apply(_slope, raw=True)


# ══════════════════════════════════════════════════════════════════════════════
#  CARGA DE CSV → DataFrame con columnas tipadas
# ══════════════════════════════════════════════════════════════════════════════

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=range(11))  # drop 'ignore'
    df.columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "num_trades",
        "taker_buy_base", "taker_buy_quote",
    ]
    for c in ["open", "high", "low", "close", "volume",
              "quote_vol", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    df["num_trades"] = df["num_trades"].astype(int)
    df["open_time"]  = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time").sort_index()
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  MERGE MULTI-TIMEFRAME — alinea 5m y 15m al índice 1m por merge_asof
# ══════════════════════════════════════════════════════════════════════════════

def merge_htf(df_1m: pd.DataFrame, df_htf: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """Merge higher-timeframe data into 1m index (no lookahead: asof left).
    Pre-computes HTF indicators (ADX, EMA50, etc.) on the REAL HTF bars
    BEFORE merging, so repeated values don't corrupt rolling calculations.
    """
    right = df_htf.copy()

    # Pre-compute HTF indicators on real HTF bars
    right[f"adx_{suffix}"]      = adx(right["high"], right["low"], right["close"], 14)
    right[f"rsi_{suffix}"]      = rsi(right["close"], 14)
    right[f"ema50_{suffix}"]    = ema(right["close"], 50)
    right[f"ema200_{suffix}"]   = ema(right["close"], 200)
    right[f"stoch_k_{suffix}"]  = stoch_k(right["high"], right["low"], right["close"], 14)
    right[f"vol_ma20_{suffix}"] = right["volume"].rolling(20).mean()
    # EMA50 slope on HTF
    right[f"ema50_slope_{suffix}"] = (
        (right[f"ema50_{suffix}"] - right[f"ema50_{suffix}"].shift(EMA50_SLOPE_N))
        / right[f"ema50_{suffix}"].shift(EMA50_SLOPE_N).replace(0, np.nan) * 100
    )

    right = right.add_suffix(f"_{suffix}")
    right.index.name = "open_time"

    merged = pd.merge_asof(
        df_1m.reset_index(),
        right.reset_index().rename(columns={"open_time": f"open_time_{suffix}"}),
        left_on="open_time",
        right_on=f"open_time_{suffix}",
        direction="backward",
    ).set_index("open_time")
    merged.drop(columns=[f"open_time_{suffix}"], errors="ignore", inplace=True)
    return merged


# ══════════════════════════════════════════════════════════════════════════════
#  RULE-BASED SIGNAL DETECTION (reproduce lógica del bot en vectores)
# ══════════════════════════════════════════════════════════════════════════════

def detect_signal(df: pd.DataFrame) -> pd.Series:
    """
    Devuelve: 'CALL', 'PUT', o 'NEUTRAL' para cada vela.

    Diseño HÍBRIDO para ML training:
    - Condición AMPLIA (3-bar RSI window) para generar suficientes ejemplos
    - Los filtros ADX, EMA50 slope, EMA21, volumen van como FEATURES en el modelo
    - El modelo ML aprenderá qué combinaciones de features son verdaderamente predictivas

    En el bot live: RSI pullback (3-bar) → ML gate (threshold) → trade
    SIN lookahead: todo se basa en datos hasta la vela t (inclusive).
    """
    rsi_1m  = rsi(df["close"], RSI_PERIODO)

    # RSI pullback con ventana de 3 barras:
    # RSI mínimo en las últimas 3 velas < umbral Y RSI actual > nivel de reanudación
    rsi_min3 = rsi_1m.rolling(3).min()
    rsi_increasing = rsi_1m > rsi_1m.shift(1)   # RSI en subida (momentum alcista)

    vela_alcista = df["close"] > df["open"]
    vela_bajista = df["close"] < df["open"]

    pullback_call = (rsi_min3 < RSI_PULLBACK_CALL) & (rsi_1m > RSI_RESUME_CALL) & rsi_increasing
    pullback_put  = (rsi_1m.rolling(3).max() > RSI_PULLBACK_PUT) & (rsi_1m < RSI_RESUME_PUT) & ~rsi_increasing

    call_cond = pullback_call & vela_alcista
    put_cond  = pullback_put  & vela_bajista

    sig = pd.Series("NEUTRAL", index=df.index)
    sig[put_cond]  = "PUT"
    sig[call_cond] = "CALL"
    return sig


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD FEATURES
# ══════════════════════════════════════════════════════════════════════════════

def build_features(simbolo: str) -> pd.DataFrame:
    print(f"\n[{simbolo}] Construyendo features...")

    for iv in ["1m", "5m", "15m"]:
        path = os.path.join(DATA_DIR, f"{simbolo}_{iv}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Falta {path} — ejecuta download_data.py primero")

    df_1m  = load_csv(os.path.join(DATA_DIR, f"{simbolo}_1m.csv"))
    df_5m  = load_csv(os.path.join(DATA_DIR, f"{simbolo}_5m.csv"))
    df_15m = load_csv(os.path.join(DATA_DIR, f"{simbolo}_15m.csv"))

    # Merge HTF
    df = merge_htf(df_1m, df_5m,  "5m")
    df = merge_htf(df,    df_15m, "15m")
    print(f"  Merged: {len(df):,} filas 1m")

    c  = df["close"]
    h  = df["high"]
    l  = df["low"]
    o  = df["open"]
    v  = df["volume"]

    # ── 3.1 Momentum ──────────────────────────────────────────────────────
    df["rsi_1m_14"]       = rsi(c, 14)
    df["rsi_1m_7"]        = rsi(c, 7)
    df["rsi_5m_14"]       = df["rsi_5m_5m"]        # pre-computed on real 5m bars
    df["rsi_15m_14"]      = df["rsi_15m_15m"]       # pre-computed on real 15m bars
    df["rsi_divergencia"] = df["rsi_1m_14"] - df["rsi_5m_14"]
    df["macd_hist_1m"]    = macd_hist(c)
    df["stoch_k_5m"]      = df["stoch_k_5m_5m"]    # pre-computed on real 5m bars
    df["cci_1m_20"]       = cci(h, l, c)

    # ── 3.2 Tendencia ─────────────────────────────────────────────────────
    ema21_val              = ema(c, 21)
    ema50_15m_val          = df["ema50_15m_15m"]    # pre-computed on real 15m bars
    ema200_15m_val         = df["ema200_15m_15m"]   # pre-computed on real 15m bars

    df["ema21_dist"]       = (c - ema21_val) / ema21_val.replace(0, np.nan) * 100
    df["ema50_15m_slope"]  = df["ema50_slope_15m_15m"]  # pre-computed on real 15m bars
    df["ema200_15m_dist"]  = (c - ema200_15m_val) / ema200_15m_val.replace(0, np.nan) * 100
    df["precio_sobre_ema"] = (c > ema50_15m_val).astype(int)

    # Higher-highs / higher-lows count (estructura de tendencia alcista)
    hh = (h > h.shift(1)).astype(int)
    hl = (l > l.shift(1)).astype(int)
    df["hh_hl_count"]      = (hh + hl).rolling(10).sum()

    # ── 3.3 Volatilidad / Régimen ─────────────────────────────────────────
    log_ret               = np.log(c / c.shift(1))
    df["atr_1m_14"]       = atr(h, l, c, 14)
    df["atr_pct"]         = df["atr_1m_14"] / c.replace(0, np.nan) * 100
    df["adx_5m_14"]       = df["adx_5m_5m"]        # pre-computed on real 5m bars
    df["bb_width_1m_20"]  = bb_width(c, 20)
    vol_ma20              = v.rolling(20).mean()
    df["vol_relativo_20"] = v / vol_ma20.replace(0, np.nan)
    vol5_ma20             = df["vol_ma20_5m_5m"]    # pre-computed on real 5m bars
    df["vol_relativo_5m"] = df["volume_5m"] / vol5_ma20.replace(0, np.nan)
    df["hvol_20"]         = log_ret.rolling(20).std()

    # ── 3.4 Price action / vela ───────────────────────────────────────────
    candle_range         = (h - l).replace(0, np.nan)
    body                 = (c - o).abs()
    df["body_size"]      = body / candle_range
    df["upper_shadow"]   = (h - pd.concat([c, o], axis=1).max(axis=1)) / candle_range
    df["lower_shadow"]   = (pd.concat([c, o], axis=1).min(axis=1) - l) / candle_range
    df["es_vela_alc"]    = (c > o).astype(int)
    prev_body            = body.shift(1)
    df["engulfing_bull"] = ((body > prev_body) & (c > o)).astype(int)
    df["hammer"]         = (df["lower_shadow"] > 2 * df["body_size"]).astype(int)
    nt_ma20              = df["num_trades"].rolling(20).mean()
    df["num_trades_rel"] = df["num_trades"] / nt_ma20.replace(0, np.nan)

    # ── 3.5 Smart-money volume ────────────────────────────────────────────
    df["taker_ratio"]    = df["taker_buy_base"] / v.replace(0, np.nan)
    df["taker_ma_ratio"] = df["taker_ratio"].rolling(10).mean()
    sell_vol             = v - df["taker_buy_base"]
    df["delta_vol"]      = df["taker_buy_base"] - sell_vol
    df["cvd_10"]         = df["delta_vol"].rolling(10).sum()

    # ── 3.6 Temporales (codificación cíclica) ─────────────────────────────
    hour = df.index.hour
    dow  = df.index.dayofweek
    df["hour_sin"]         = np.sin(2 * math.pi * hour / 24)
    df["hour_cos"]         = np.cos(2 * math.pi * hour / 24)
    df["dow_sin"]          = np.sin(2 * math.pi * dow  / 7)
    df["dow_cos"]          = np.cos(2 * math.pi * dow  / 7)
    df["is_london_open"]   = ((hour >= 7)  & (hour < 9)).astype(int)
    df["is_ny_open"]       = ((hour >= 13) & (hour < 15)).astype(int)
    df["is_asian_session"] = (hour < 6).astype(int)

    # ── 3.7 RSI pullback memory features ─────────────────────────────────
    rsi_1m = df["rsi_1m_14"]
    df["rsi_prev1"]          = rsi_1m.shift(1)
    df["rsi_prev2"]          = rsi_1m.shift(2)
    df["rsi_min_last_10"]    = rsi_1m.rolling(10).min()
    df["rsi_max_last_10"]    = rsi_1m.rolling(10).max()
    df["rsi_range_last_10"]  = df["rsi_max_last_10"] - df["rsi_min_last_10"]

    # Velas desde el mínimo RSI (ventana 10)
    def velas_desde_min(x):
        idx = np.argmin(x)
        return len(x) - 1 - idx
    df["velas_desde_rsi_min"] = rsi_1m.rolling(10).apply(velas_desde_min, raw=True).clip(1)

    df["rsi_recovery_vel"] = (rsi_1m - df["rsi_min_last_10"]) / df["velas_desde_rsi_min"]
    df["rsi_slope_3"]      = linreg_slope(rsi_1m, 3)

    # ── 3.8 Señal rule-based y label ─────────────────────────────────────
    df["signal"] = detect_signal(df)

    # Label: 1 si el precio sube DURACION_VELAS velas adelante
    # Para PUT: 1 si baja. Creamos label_call y label_put separados.
    fut_close           = c.shift(-DURACION_VELAS)
    df["label_call"]    = (fut_close > c).astype(int)
    df["label_put"]     = (fut_close < c).astype(int)

    # Precio futuro para diagnóstico
    df["future_ret_pct"] = (fut_close - c) / c * 100

    print(f"  Total filas: {len(df):,}")
    print(f"  CALL signals: {(df['signal']=='CALL').sum()}")
    print(f"  PUT  signals: {(df['signal']=='PUT').sum()}")

    # Eliminar últimas DURACION_VELAS filas (sin label válido)
    df = df.iloc[:-DURACION_VELAS]
    # Eliminar warmup
    df = df.iloc[WARMUP_CANDLES:]

    return df


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for sym in ["ETHUSDT", "BTCUSDT", "SOLUSDT"]:
        try:
            df = build_features(sym)
            out = os.path.join(OUTPUT_DIR, f"features_{sym}.parquet")
            df.to_parquet(out)
            print(f"  -> {out}  ({len(df):,} filas, {df.shape[1]} cols)")
        except FileNotFoundError as e:
            print(f"[{sym}] Saltando: {e}")
