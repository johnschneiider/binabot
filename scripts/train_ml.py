"""
PIPELINE ML — Sniper Pullback ML v1.0
Entrena LightGBM (+ XGBoost de referencia) para predecir P(win) de señales CALL y PUT.

Diseño:
  - Separación temporal estricta: Train 70% / Val 15% / Test 15%
  - Threshold seleccionado por P&L esperado (no accuracy)
  - Calibración isotónica de probabilidades
  - Guarda modelo, scaler, threshold en models/

Uso:
    python scripts/train_ml.py
"""

import os
import sys
import json
import numpy as np
import pandas as pd
import joblib
import warnings
warnings.filterwarnings("ignore")

from sklearn.impute import SimpleImputer
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import TimeSeriesSplit
import lightgbm as lgb
import xgboost as xgb
import matplotlib
matplotlib.use("Agg")   # sin GUI (headless)
import matplotlib.pyplot as plt

# ── Shared ML classes (pickling-safe: stored under 'ml_helper.*') ────────────
import sys, os as _os
sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), ".."))
from ml_helper import IsotonicCalibrated, EnsembleModel  # noqa: F401

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
MODEL_DIR  = os.path.join(os.path.dirname(__file__), "..", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

STAKE  = 1.0
PAYOUT = 0.95

# ─── features a usar (excluir columnas de metadata) ──────────────────────────
EXCLUDE = {
    "open", "high", "low", "close", "volume",
    "close_time", "quote_vol", "num_trades", "taker_buy_base", "taker_buy_quote",
    "open_5m", "high_5m", "low_5m", "close_5m", "volume_5m",
    "close_time_5m", "quote_vol_5m", "num_trades_5m",
    "taker_buy_base_5m", "taker_buy_quote_5m",
    "open_15m", "high_15m", "low_15m", "close_15m", "volume_15m",
    "close_time_15m", "quote_vol_15m", "num_trades_15m",
    "taker_buy_base_15m", "taker_buy_quote_15m",
    "signal", "label_call", "label_put", "future_ret_pct",
}


def expected_pnl(prob: float, stake=STAKE, payout=PAYOUT) -> float:
    return prob * payout * stake - (1 - prob) * stake


def get_feature_cols(df: pd.DataFrame) -> list:
    return [c for c in df.columns if c not in EXCLUDE]


# ══════════════════════════════════════════════════════════════════════════════
#  PREPROCESAMIENTO
# ══════════════════════════════════════════════════════════════════════════════

def split_temporal(df: pd.DataFrame):
    n     = len(df)
    i70   = int(n * 0.70)
    i85   = int(n * 0.85)
    train = df.iloc[:i70]
    val   = df.iloc[i70:i85]
    test  = df.iloc[i85:]
    return train, val, test


def prepare_xy(df: pd.DataFrame, label_col: str, feat_cols: list):
    X = df[feat_cols].values.astype(np.float32)
    y = df[label_col].values.astype(int)
    return X, y


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRENAMIENTO LIGHTGBM
# ══════════════════════════════════════════════════════════════════════════════

LGBM_PARAMS = {
    "n_estimators":    1000,
    "learning_rate":   0.02,
    "max_depth":       5,
    "num_leaves":      31,
    "min_child_samples": 30,
    "subsample":       0.8,
    "colsample_bytree": 0.7,
    "class_weight":    "balanced",
    "random_state":    42,
    "n_jobs":          -1,
    "verbose":         -1,
}


def train_lgbm(X_tr, y_tr, X_val, y_val):
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(
        X_tr, y_tr,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
    )
    return model


def train_xgb(X_tr, y_tr, X_val, y_val):
    neg = (y_tr == 0).sum()
    pos = (y_tr == 1).sum()
    sw  = neg / pos if pos > 0 else 1.0
    model = xgb.XGBClassifier(
        n_estimators=1000,
        learning_rate=0.02,
        max_depth=5,
        min_child_weight=30,
        subsample=0.8,
        colsample_bytree=0.7,
        scale_pos_weight=sw,
        random_state=42,
        n_jobs=-1,
        eval_metric="logloss",
        early_stopping_rounds=50,
        verbosity=0,
    )
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
    return model


# ══════════════════════════════════════════════════════════════════════════════
#  SELECCIÓN DE THRESHOLD POR P&L
# ══════════════════════════════════════════════════════════════════════════════

def select_threshold(probs: np.ndarray, labels: np.ndarray,
                     stake=STAKE, payout=PAYOUT, min_ops: int = 5,
                     target_wr: float = 0.68):
    """
    Select threshold targeting `target_wr` on val (to absorb ~5% shift to test).
    Strategy:
      1. Among thresholds with WR >= target_wr AND ops >= min_ops, pick the
         one with the most operations (lowest threshold → more trades).
      2. If none meet target_wr, fall back to the threshold with max WR
         (still with ops >= min_ops).
    """
    results = []
    for thr in np.arange(0.45, 0.85, 0.01):
        mask  = probs >= thr
        n_ops = int(mask.sum())
        if n_ops < min_ops:
            continue
        wr  = float(labels[mask].mean())
        pnl = n_ops * expected_pnl(wr, stake, payout)
        results.append({"thr": round(thr, 2), "ops": n_ops, "wr": wr, "pnl": pnl})

    if not results:
        return 0.50, 0.0, pd.DataFrame()

    df = pd.DataFrame(results)
    candidates = df[df["wr"] >= target_wr]
    if len(candidates) > 0:
        # Most ops (lowest thr) that still hits target_wr
        row = candidates.iloc[0]
    else:
        # Fallback: highest WR achievable
        row = df.loc[df["wr"].idxmax()]

    return float(row["thr"]), float(row["wr"]), df


# ══════════════════════════════════════════════════════════════════════════════
#  PLOTS
# ══════════════════════════════════════════════════════════════════════════════

def plot_calibration(probs, labels, title, path):
    frac_pos, mean_pred = calibration_curve(labels, probs, n_bins=10)
    plt.figure(figsize=(5, 4))
    plt.plot(mean_pred, frac_pos, "s-", label="Model")
    plt.plot([0, 1], [0, 1], "k--", label="Perfect")
    plt.title(title)
    plt.xlabel("Mean predicted probability")
    plt.ylabel("Fraction of positives")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=100)
    plt.close()
    print(f"  Plot: {path}")


def plot_feature_importance(model, feat_cols, path, top_n=25):
    imp = pd.Series(model.feature_importances_, index=feat_cols).sort_values(ascending=False)
    plt.figure(figsize=(8, 6))
    imp.head(top_n).plot(kind="barh")
    plt.gca().invert_yaxis()
    plt.title("Feature Importance (gain)")
    plt.tight_layout()
    plt.savefig(path, dpi=100)
    plt.close()
    print(f"  Plot: {path}")


def plot_threshold_sweep(df_thr, title, path):
    fig, ax1 = plt.subplots(figsize=(8, 4))
    ax2 = ax1.twinx()
    ax1.plot(df_thr["thr"], df_thr["wr"]*100,  "b-o", ms=4, label="WR %")
    ax2.plot(df_thr["thr"], df_thr["pnl"],      "r-s", ms=4, label="P&L $")
    ax1.set_xlabel("Threshold")
    ax1.set_ylabel("Win Rate (%)", color="b")
    ax2.set_ylabel("P&L ($)", color="r")
    ax1.set_ylim(40, 90)
    plt.title(title)
    fig.tight_layout()
    plt.savefig(path, dpi=100)
    plt.close()
    print(f"  Plot: {path}")


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(simbolo: str, direction: str):
    """
    direction: 'CALL' o 'PUT'
    Filtra solo filas donde signal == direction, entrena, evalúa, guarda.
    """
    label_col = f"label_{direction.lower()}"
    parquet   = os.path.join(DATA_DIR, f"features_{simbolo}.parquet")

    if not os.path.exists(parquet):
        print(f"[{simbolo}/{direction}] Sin features — ejecuta feature_engineering.py")
        return None

    df_all = pd.read_parquet(parquet)
    df_sig = df_all[df_all["signal"] == direction].copy()

    if len(df_sig) < 100:
        print(f"[{simbolo}/{direction}] Solo {len(df_sig)} señales — insuficiente")
        return None

    print(f"\n{'='*60}")
    print(f"PIPELINE: {simbolo} / {direction}  —  {len(df_sig)} señales")
    print(f"{'='*60}")

    feat_cols = get_feature_cols(df_all)
    train, val, test = split_temporal(df_sig)
    print(f"  Train: {len(train)}  Val: {len(val)}  Test: {len(test)}")
    print(f"  Periodo train: {train.index[0].date()} → {train.index[-1].date()}")
    print(f"  Periodo test:  {test.index[0].date()} → {test.index[-1].date()}")

    # Imputar NaN
    imp = SimpleImputer(strategy="median")
    X_tr  = imp.fit_transform(train[feat_cols].values.astype(np.float32))
    X_val = imp.transform(val[feat_cols].values.astype(np.float32))
    X_te  = imp.transform(test[feat_cols].values.astype(np.float32))
    y_tr, y_val, y_te = (
        train[label_col].values,
        val[label_col].values,
        test[label_col].values,
    )

    wr_base = y_tr.mean()
    print(f"  WR baseline train: {wr_base*100:.1f}%")

    # ── LightGBM ────────────────────────────────────────────────────────
    print("\n  [LightGBM]")
    lgbm_raw = train_lgbm(X_tr, y_tr, X_val, y_val)
    print(f"    Best iter: {lgbm_raw.best_iteration_}")

    # Calibración isotónica manual sobre validation
    lgbm_cal = IsotonicCalibrated(lgbm_raw).fit(X_val, y_val)

    prob_val_lgbm = lgbm_cal.predict_proba(X_val)[:, 1]
    auc_lgbm      = roc_auc_score(y_val, prob_val_lgbm)
    print(f"    AUC val: {auc_lgbm:.4f}")

    # ── XGBoost (referencia) ─────────────────────────────────────────────
    print("\n  [XGBoost]")
    xgb_raw = train_xgb(X_tr, y_tr, X_val, y_val)
    xgb_cal = IsotonicCalibrated(xgb_raw).fit(X_val, y_val)
    prob_val_xgb = xgb_cal.predict_proba(X_val)[:, 1]
    auc_xgb      = roc_auc_score(y_val, prob_val_xgb)
    print(f"    AUC val: {auc_xgb:.4f}")

    # ── Ensemble AUC-ponderado ───────────────────────────────────────────
    total_auc = auc_lgbm + auc_xgb
    w_lgbm    = auc_lgbm / total_auc
    w_xgb     = auc_xgb  / total_auc
    ensemble  = EnsembleModel(lgbm_cal, xgb_cal, weight_a=w_lgbm)
    prob_val_ens = ensemble.predict_proba(X_val)[:, 1]
    auc_ens      = roc_auc_score(y_val, prob_val_ens)
    print(f"\n  [Ensemble AUC-weighted]")
    print(f"    w_lgbm={w_lgbm:.2f}  w_xgb={w_xgb:.2f}  AUC val: {auc_ens:.4f}")

    # Siempre usar ensemble como modelo final (más robusto y mejor calibrado)
    best_model, best_probs_val, best_name = ensemble, prob_val_ens, "ensemble"
    base_model_for_imp = lgbm_raw if auc_lgbm >= auc_xgb else xgb_raw

    print(f"\n  Modelo final: ENSEMBLE LGBM+XGB")

    # ── Threshold sweep en VAL (target WR >= 68%) ────────────────────────
    thr, val_wr, df_thr = select_threshold(best_probs_val, y_val, target_wr=0.68)
    print(f"\n  Threshold óptimo (val): {thr}  →  WR_val={val_wr*100:.1f}%")
    if not df_thr.empty:
        row = df_thr[df_thr["thr"] == thr].iloc[0]
        print(f"    WR={row['wr']*100:.1f}%  ops={row['ops']}")

    # ── Evaluación en TEST (tocar UNA VEZ) ──────────────────────────────
    prob_te = best_model.predict_proba(X_te)[:, 1]
    mask_te = prob_te >= thr
    ops_te  = mask_te.sum()

    print(f"\n  [TEST SET — resultado final]")
    if ops_te > 0:
        wr_te  = y_te[mask_te].mean()
        pnl_te = ops_te * expected_pnl(wr_te)
        auc_te = roc_auc_score(y_te, prob_te) if len(np.unique(y_te)) > 1 else 0
        print(f"    AUC:      {auc_te:.4f}")
        print(f"    Ops >thr: {ops_te}")
        print(f"    WR:       {wr_te*100:.1f}%")
        print(f"    P&L:      ${pnl_te:.2f}")
        if wr_te >= 0.70:
            print("    ✓ EXCELENTE — WR >= 70%")
        elif wr_te >= 0.63:
            print("    ✓ BUENO — WR >= 63%")
        else:
            print("    ! Por debajo del objetivo 63%")
    else:
        print(f"    Sin operaciones con threshold {thr}")
        wr_te, pnl_te = 0.0, 0.0

    # ── Plots ────────────────────────────────────────────────────────────
    tag = f"{simbolo}_{direction.lower()}"
    plot_calibration(
        best_probs_val, y_val,
        f"Calibración {tag} (val)",
        os.path.join(MODEL_DIR, f"calibration_{tag}.png"),
    )
    plot_threshold_sweep(
        df_thr,
        f"Threshold sweep {tag} (val)",
        os.path.join(MODEL_DIR, f"threshold_{tag}.png"),
    )
    if best_name == "lgbm" or True:   # always save feature importance for diagnostic
        plot_feature_importance(
            base_model_for_imp, feat_cols,
            os.path.join(MODEL_DIR, f"importance_{tag}.png"),
        )

    # ── Guardar modelo y artefactos ──────────────────────────────────────
    model_path     = os.path.join(MODEL_DIR, f"{best_name}_{tag}.pkl")
    imputer_path   = os.path.join(MODEL_DIR, f"imputer_{tag}.pkl")
    threshold_path = os.path.join(MODEL_DIR, f"threshold_{tag}.txt")
    feat_path      = os.path.join(MODEL_DIR, f"features_{tag}.json")

    joblib.dump(best_model, model_path)   # EnsembleModel(lgbm_cal, xgb_cal)
    joblib.dump(imp, imputer_path)
    with open(threshold_path, "w") as f:
        f.write(str(thr))
    with open(feat_path, "w") as f:
        json.dump(feat_cols, f)

    print(f"\n  Guardado: {model_path}")
    print(f"  Threshold: {thr}  →  {threshold_path}")

    return {
        "simbolo": simbolo,
        "direction": direction,
        "model": best_name,
        "auc_val": auc_ens,
        "threshold": thr,
        "wr_test": wr_te,
        "ops_test": ops_te,
        "pnl_test": pnl_te,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-VALIDATION TEMPORAL (diagnóstico adicional)
# ══════════════════════════════════════════════════════════════════════════════

def cross_val_temporal(simbolo: str, direction: str, n_splits: int = 5):
    label_col = f"label_{direction.lower()}"
    parquet   = os.path.join(DATA_DIR, f"features_{simbolo}.parquet")
    if not os.path.exists(parquet):
        return

    df_all = pd.read_parquet(parquet)
    df_sig = df_all[df_all["signal"] == direction].copy()
    if len(df_sig) < 200:
        return

    feat_cols = get_feature_cols(df_all)
    X = df_sig[feat_cols].values.astype(np.float32)
    y = df_sig[label_col].values

    tscv   = TimeSeriesSplit(n_splits=n_splits)
    aucs   = []
    wrs    = []
    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X[tr_idx], X[val_idx]
        y_tr, y_val = y[tr_idx], y[val_idx]
        imp = SimpleImputer(strategy="median")
        X_tr  = imp.fit_transform(X_tr)
        X_val = imp.transform(X_val)
        m = lgb.LGBMClassifier(**LGBM_PARAMS)
        m.fit(X_tr, y_tr,
              eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)])
        p   = m.predict_proba(X_val)[:, 1]
        auc = roc_auc_score(y_val, p) if len(np.unique(y_val)) > 1 else 0.5
        thr_f, _, _ = select_threshold(p, y_val, min_ops=3)
        wr = y_val[p >= thr_f].mean() if (p >= thr_f).sum() > 0 else 0
        aucs.append(auc)
        wrs.append(wr)
        print(f"    Fold {fold+1}: AUC={auc:.3f}  WR@thr={wr*100:.1f}%")

    print(f"  CV AUC: {np.mean(aucs):.3f} ± {np.std(aucs):.3f}")
    print(f"  CV WR:  {np.mean(wrs)*100:.1f}% ± {np.std(wrs)*100:.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    combos = [
        ("ETHUSDT", "CALL"),
        ("ETHUSDT", "PUT"),
        ("BTCUSDT", "CALL"),
        ("SOLUSDT", "CALL"),
    ]
    summary = []
    for sym, direc in combos:
        print(f"\n{'#'*60}")
        print(f"  Cross-Validation temporal — {sym}/{direc}")
        print(f"{'#'*60}")
        cross_val_temporal(sym, direc, n_splits=5)

        result = run_pipeline(sym, direc)
        if result:
            summary.append(result)

    print(f"\n\n{'='*60}")
    print("RESUMEN FINAL")
    print(f"{'='*60}")
    for r in summary:
        print(f"  {r['simbolo']:10} {r['direction']:4}  "
              f"AUC={r['auc_val']:.3f}  "
              f"thr={r['threshold']}  "
              f"WR_test={r['wr_test']*100:.1f}%  "
              f"P&L_test=${r['pnl_test']:.2f}")
