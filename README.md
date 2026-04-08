# Bot Cuantitativo Deriv (Django) — Sniper Pullback ML v2

Bot de trading Binance Futures con estrategia multi-timeframe + ML gate (LightGBM + XGBoost ensemble).

## Arquitectura
```
RSI pullback 1m (señal amplia)
      │
      ▼ ADX 5m ≥ 28 + EMA50 slope 15m ≥ 0.03%
      │
      ▼ ML Gate (Ensemble LGBM+XGB, threshold óptimo por WR)
      │
      ▼ Orden Binance Futures (USDT-M, 20x)
```

## Resultados (test out-of-sample 30 días, Abr 2026)
| Activo | Dirección | WR test | AUC | Thr | Ops/30d |
|--------|-----------|---------|-----|-----|--------|
| ETH    | CALL      | **69.0%** | 0.766 | 0.51 | 155 |
| ETH    | PUT       | 60.5%   | 0.759 | 0.47 | 271 |
| BTC    | CALL      | **72.5%** | 0.759 | 0.59 | 120 |

**CV WR (5-fold temporal):** ETH CALL 68.5% ±0.3%, BTC CALL 68.7% ±0.8%
**WR baseline** (sin ML): ETH 58.3%, BTC 38.6%

## Pipeline ML
```
scripts/download_data.py     → data/ETHUSDT_1m/5m/15m.csv (180 días)
scripts/feature_engineering.py → data/features_ETHUSDT.parquet (60 features)
scripts/train_ml.py          → models/ensemble_ETHUSDT_call.pkl (LGBM+XGB)
binance_bot_django.py        → ML gate integrado, ETH + BTC activos
```

## Modelos generados
```
models/ensemble_ETHUSDT_call.pkl  (769 KB)
models/ensemble_ETHUSDT_put.pkl   (843 KB)
models/ensemble_BTCUSDT_call.pkl  (961 KB)
models/threshold_*.txt            thresholds óptimos por WR
models/imputer_*.pkl              SimpleImputer(median) para NaNs
models/features_*.json            orden de 60 features
```

## Instalación y uso

### 1. Entorno virtual
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install lightgbm xgboost shap pandas-ta pyarrow joblib
```

### 2. Configurar API
```bash
copy env.example .env
# Editar .env con BINANCE_API_KEY y BINANCE_API_SECRET
```

### 3. Descargar datos y entrenar (primera vez)
```powershell
python scripts/download_data.py
python scripts/feature_engineering.py
python scripts/train_ml.py
```

### 4. Iniciar bot
```powershell
python binance_bot_django.py
```

## Parámetros clave
| Parámetro | Valor | Razón |
|-----------|-------|-------|
| `DURACION_SEG` | 900 (15 min) | Hold para desarrollo de momentum |
| `ADX_MIN` | 28 | Mercado trending fuerte |
| `EMA50_SLOPE_MIN` | 0.03% | Tendencia macro confirmada |
| `MAX_OPS_DIA` | 10 | Calidad > cantidad |
| `LOSS_STREAK_LIMIT` | 3 | Circuit breaker |

## Arquitectura módulos Django
- `vector_variables`: vector de estado del mercado
- `vector_pesos`: estrategia y pesos
- `gestion_riesgo`: riesgo (innegociable)

