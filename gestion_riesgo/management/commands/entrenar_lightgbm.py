from __future__ import annotations

import json
import math
import pickle
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from lightgbm import LGBMClassifier

from gestion_riesgo.models import TickDerivHistorico


@dataclass
class TrainMeta:
    symbol: str
    horizon_ticks: int
    payout_win: float
    threshold: float
    features: List[str]
    n_train: int
    n_valid: int
    ev_best: float
    wr_best: float
    n_pred_best: int
    step: int


def _load_ticks(symbol: str, step: int) -> pd.DataFrame:
    qs = (
        TickDerivHistorico.objects.filter(cuenta__simbolo=symbol)
        .order_by("epoch")
        .values_list("epoch", "precio")
    )
    total = qs.count()
    if total == 0:
        raise ValueError(f"Sin datos para {symbol}")
    xs = []
    ys = []
    idx = 0
    for epoch, precio in qs.iterator(chunk_size=5000):
        if idx % step == 0:
            xs.append(int(epoch))
            ys.append(float(precio))
        idx += 1
    df = pd.DataFrame({"epoch": xs, "price": ys})
    return df


def _build_features(df: pd.DataFrame, horizon: int) -> Tuple[pd.DataFrame, np.ndarray]:
    price = df["price"]
    df_feat = pd.DataFrame(index=df.index)

    # EMAs
    df_feat["price"] = price
    df_feat["ema50"] = price.ewm(span=50, adjust=False).mean()
    df_feat["ema100"] = price.ewm(span=100, adjust=False).mean()
    df_feat["ema200"] = price.ewm(span=200, adjust=False).mean()
    df_feat["gap"] = df_feat["ema50"] - df_feat["ema100"]
    df_feat["gap_rel"] = df_feat["gap"] / (df_feat["ema100"].abs() + 1e-6)
    df_feat["slope50_10"] = df_feat["ema50"] - df_feat["ema50"].shift(10)

    returns = price.diff()
    df_feat["ret1"] = returns
    df_feat["ret5"] = price.diff(5)
    df_feat["ret20"] = price.diff(20)
    df_feat["ret_std_50"] = returns.rolling(50).std()
    df_feat["z_price_ema50"] = (price - df_feat["ema50"]) / (df_feat["ret_std_50"] + 1e-8)

    # Choppy: conteo de cambios de signo en ventana 40
    sign_rel = np.sign(price - df_feat["ema50"]).replace(0, 1)
    flips = (sign_rel != sign_rel.shift(1)).astype(int)
    df_feat["flips40"] = flips.rolling(40).sum()

    # Etiqueta a horizonte
    future = price.shift(-horizon)
    y = (future > price).astype(int)

    df_feat = df_feat.dropna()
    y = y.loc[df_feat.index]
    return df_feat, y.to_numpy(dtype=int)


def _split_train_valid(dfX: pd.DataFrame, y: np.ndarray, frac_train: float = 0.8):
    n = len(dfX)
    n_tr = max(1000, int(n * frac_train))
    X_train = dfX.iloc[:n_tr]
    y_train = y[:n_tr]
    X_val = dfX.iloc[n_tr:]
    y_val = y[n_tr:]
    return X_train, y_train, X_val, y_val


def _search_threshold(y_true: np.ndarray, prob: np.ndarray, payout: float) -> Tuple[float, float, float, int]:
    best_thr = 0.5
    best_ev = -1e9
    best_wr = 0.0
    best_n = 0
    for thr in np.linspace(0.5, 0.85, 20):
        mask = prob >= thr
        n_pred = int(mask.sum())
        if n_pred < 100:
            continue
        wins = int(((y_true == 1) & mask).sum())
        wr = wins / n_pred
        ev = (wr * payout) - (1 - wr)
        if ev > best_ev:
            best_ev = ev
            best_thr = float(thr)
            best_wr = wr
            best_n = n_pred
    if best_n == 0:
        best_n = int(len(prob))
        best_wr = float((prob >= 0.5).mean())
        best_ev = (best_wr * payout) - (1 - best_wr)
    return best_thr, best_ev, best_wr, best_n


class Command(BaseCommand):
    help = "Entrena un modelo LightGBM para predecir direccionalidad a horizonte de ticks."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", type=str, default="R_10", help="Símbolo (R_10 o R_100)")
        parser.add_argument("--horizon", type=int, default=10, help="Horizonte en ticks (default 10)")
        parser.add_argument("--payout", type=float, default=0.8857, help="Payout ganador (stake=1)")
        parser.add_argument("--max-points", type=int, default=400000, help="Máximo de puntos a muestrear (stride)")
        parser.add_argument("--outdir", type=str, default="models", help="Directorio de salida")

    def handle(self, *args, **opts):
        symbol = str(opts.get("symbol") or "R_10").strip()
        horizon = int(opts.get("horizon") or 10)
        payout = float(opts.get("payout") or 0.8857)
        max_points = max(10000, int(opts.get("max_points") or 400000))
        outdir = Path(str(opts.get("outdir") or "models")).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
        status_path = outdir / f"train_status_{symbol}.json"

        def write_status(status: str, progress: float, message: str = "") -> None:
            try:
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump({"status": status, "progress": progress, "message": message}, f)
            except Exception:
                pass

        self.stdout.write(f"[TRAIN] symbol={symbol} horizon={horizon} ticks")
        write_status("running", 0.05, "Iniciando...")

        # stride para limitar puntos
        total = TickDerivHistorico.objects.filter(cuenta__simbolo=symbol).count()
        if total == 0:
            self.stdout.write(self.style.ERROR(f"Sin datos para {symbol}"))
            write_status("error", 1.0, "Sin datos")
            return
        step = max(1, math.ceil(total / max_points))
        self.stdout.write(f"[DATA] total={total} usando stride={step} => ~{int(total/step)} puntos")
        write_status("running", 0.15, f"Leyendo datos (stride={step})")

        df = _load_ticks(symbol, step)
        write_status("running", 0.3, "Construyendo features")
        df_feat, y = _build_features(df, horizon)
        write_status("running", 0.45, "Split train/val")
        X_train, y_train, X_val, y_val = _split_train_valid(df_feat, y, frac_train=0.8)

        self.stdout.write(f"[SPLIT] train={len(X_train)} val={len(X_val)}")
        if len(X_train) < 1000 or len(X_val) < 500:
            self.stdout.write(self.style.ERROR("Muy pocos datos después del muestreo. Ajusta max-points o revisa la BD."))
            write_status("error", 1.0, "Datos insuficientes")
            return

        model = LGBMClassifier(
            n_estimators=400,
            learning_rate=0.03,
            max_depth=6,
            num_leaves=48,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        write_status("running", 0.6, "Entrenando LightGBM")
        model.fit(X_train, y_train)
        prob_val = model.predict_proba(X_val)[:, 1]

        write_status("running", 0.8, "Buscando umbral por EV")
        thr, ev_best, wr_best, n_pred = _search_threshold(y_val, prob_val, payout)
        self.stdout.write(
            f"[THR] best_thr={thr:.3f} ev={ev_best:.4f} wr={wr_best*100:.2f}% n_pred={n_pred} payout={payout}"
        )

        artifact = {
            "model": model,
            "threshold": thr,
            "meta": asdict(
                TrainMeta(
                    symbol=symbol,
                    horizon_ticks=horizon,
                    payout_win=payout,
                    threshold=thr,
                    features=list(df_feat.columns),
                    n_train=len(X_train),
                    n_valid=len(X_val),
                    ev_best=ev_best,
                    wr_best=wr_best,
                    n_pred_best=n_pred,
                    step=step,
                )
            ),
        }

        out_pkl = outdir / f"lgbm_{symbol}_h{horizon}_ticks.pkl"
        with open(out_pkl, "wb") as f:
            pickle.dump(artifact, f)

        out_meta = outdir / f"lgbm_{symbol}_h{horizon}_ticks.meta.json"
        with open(out_meta, "w", encoding="utf-8") as f:
            json.dump(artifact["meta"], f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"Guardado: {out_pkl}"))
        self.stdout.write(f"Meta: {out_meta}")
        write_status("done", 1.0, f"Listo: {out_pkl.name}")

